"""Prepared prompts stay dev-only; one call answers them at most once."""

import argparse
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
import importlib.util
import itertools
import json
from pathlib import Path
import re
import shlex
import shutil
import socket
import sys
from tempfile import TemporaryDirectory
import threading
from typing import Any, cast, NamedTuple, Protocol

import pytest

from dfilterforge import cli as cli_module
from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import content_sha256
from dfilterforge.catalog_runtime import DEFAULT_CATALOG_PATH
from dfilterforge.catalog_runtime import freeze_catalog
from dfilterforge.completions import CompletionBatchV1
from dfilterforge.completions import CompletionStatusV1
from dfilterforge.completions import PrepareManifestV1
from dfilterforge.completions import RequestSettingsV1
from dfilterforge.completions import RunManifestV1
from dfilterforge.completions import TokenPricesV1
from dfilterforge.field_catalog import FieldType
from dfilterforge.field_retrieval import FieldRetrievalError
from dfilterforge.field_retrieval import FieldRetrievalItemV1
from dfilterforge.field_retrieval import FieldRetrievalResultV1
from dfilterforge.generation import condition_label
from dfilterforge.generation import DirectFilterResultV1
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import PreparedPromptV1
from dfilterforge.generation import RetrievedFieldV1
from dfilterforge.intent_ir import GenerationResultV1
from dfilterforge.intent_ir import GenerationStatus
from dfilterforge.model_cases import ModelNonReadyCaseV1
from dfilterforge.model_client import API_KEY_ENV
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import GoldCase
from dfilterforge.model_split import model_semantic_cases
from dfilterforge.model_split import ModelGoldCaseV1
from dfilterforge.model_split import ModelInputItemV1
from dfilterforge.run_store import check_manifest
from dfilterforge.run_store import check_prepare
from dfilterforge.run_store import check_splits
from dfilterforge.run_store import load_run
from dfilterforge.runner import TsharkRunner
from dfilterforge.scoring import score_run

_LABELS = ("C1", "C2", "C3", "C4")
_LEXICAL_LABELS = ("C2", "C4")
# Prepare selects the dev items: the ready block, then the non-ready one.
_DEV_ITEM_IDS = tuple(
    f"mei-{index:04d}" for index in (*range(1, 25), *range(501, 517))
)
_DEV_ITEMS = len(_DEV_ITEM_IDS)
# One request per dev item and condition.
_PASS_REQUESTS = len(_LABELS) * _DEV_ITEMS
_INPUT_PREFIX = "INPUT_JSON\n"


class _Retrieve(Protocol):
    """Typed view of the retrieval entry point the script calls."""

    def __call__(
        self,
        path: Path,
        items: Sequence[FieldRetrievalItemV1],
        *,
        top_k: int = 16,
    ) -> tuple[FieldRetrievalResultV1, ...]:
        ...


class _ModelRun(Protocol):
    """Typed view of the standalone model-run script."""

    retrieve_fields: _Retrieve

    def build_parser(self) -> argparse.ArgumentParser:
        ...

    def main(self, argv: Sequence[str] | None = None) -> int:
        ...


def _load_model_run() -> _ModelRun:
    path = Path(__file__).parents[1] / "scripts" / "model_run.py"
    spec = importlib.util.spec_from_file_location("model_run", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("model run script cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast(_ModelRun, module)


model_run = _load_model_run()


class _Catalog(NamedTuple):
    """One frozen fixture inventory and the identity it recorded."""

    path: Path
    catalog_hash: str


class _FakeRunner(TsharkRunner):
    """Serves catalog reports shaped like the real tshark inventory."""

    def version(self) -> str:
        return "4.6.8"

    def report(self, name: str) -> bytes:
        if name == "fields":
            return b"".join(
                line.encode("utf-8")
                for line in (
                    "P\tInternet Protocol Version 4\tip\n",
                    "P\tTransmission Control Protocol\ttcp\n",
                    "P\tUser Datagram Protocol\tudp\n",
                    "P\tDomain Name System\tdns\n",
                    "F\tTime to Live\tip.ttl\tFT_UINT8\tip\tBASE_DEC\n",
                    "F\tDestination Address\tip.dst\tFT_IPv4\tip\tBASE_NONE\n",
                    "F\tDestination Port\ttcp.dstport\tFT_UINT16\ttcp\t"
                    "BASE_DEC\n",
                    "F\tAcknowledgment\ttcp.flags.ack\tFT_BOOLEAN\ttcp\t8\n",
                    "F\tSyn\ttcp.flags.syn\tFT_BOOLEAN\ttcp\t8\n",
                    "F\tFin\ttcp.flags.fin\tFT_BOOLEAN\ttcp\t8\n",
                    "F\tECN-Echo\ttcp.flags.ece\tFT_BOOLEAN\ttcp\t8\n",
                    "F\tResponse\tdns.flags.response\tFT_BOOLEAN\tdns\t16\n",
                    "F\tType\tdns.qry.type\tFT_UINT16\tdns\tBASE_DEC\n",
                    "F\tReply code\tdns.flags.rcode\tFT_UINT16\tdns\t"
                    "BASE_DEC\n",
                    "F\tIPV4\tbacapp.IPV4\tFT_IPv4\tbacapp\tBASE_NONE\n",
                    "F\tDownstream IPv4 TTL\tmpls_echo.tlv.ilso_ipv4.ttl\t"
                    "FT_UINT8\tmpls_echo\tBASE_DEC\n",
                )
            )
        if name == "values":
            return b"V\tdns.qry.type\t1\tA\nV\tdns.qry.type\t28\tAAAA\n"
        return b"fixture-profile"


@pytest.fixture(name="catalog", scope="module")
def fixture_catalog(tmp_path_factory: pytest.TempPathFactory) -> _Catalog:
    """Freezes one small inventory shaped like the real field catalog."""
    path = tmp_path_factory.mktemp("catalog") / "fixture.sqlite3"
    metadata = freeze_catalog(path, _FakeRunner())
    return _Catalog(path, cast(str, metadata["catalog_hash"]))


def _no_sockets(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("this step must not open a socket")


def _prepare(catalog: Path, output_dir: Path) -> int:
    return model_run.main(
        [
            "prepare",
            "--catalog",
            str(catalog),
            "--output-dir",
            str(output_dir),
            "--source-revision",
            "test",
        ]
    )


def _batch(output_dir: Path, label: str) -> PreparedBatchV1:
    text = (output_dir / "prepared" / f"{label}.json").read_text(
        encoding="utf-8"
    )
    return PreparedBatchV1.model_validate_json(text)


def _manifest(output_dir: Path) -> PrepareManifestV1:
    text = (output_dir / "prepare.json").read_text(encoding="utf-8")
    return PrepareManifestV1.model_validate_json(text)


def _payload(prompt: PreparedPromptV1) -> dict[str, object]:
    content = prompt.messages[1].content
    assert content.startswith(_INPUT_PREFIX)
    return cast(dict[str, object], json.loads(content[len(_INPUT_PREFIX) :]))


def _files(output_dir: Path) -> dict[str, bytes]:
    return {
        path.relative_to(output_dir).as_posix(): path.read_bytes()
        for path in sorted(output_dir.rglob("*"))
        if path.is_file()
    }


def _split_digest() -> str:
    with TemporaryDirectory(prefix="dfilterforge-test-split-") as staging:
        artifacts = generate_model_split(Path(staging))
        lines = artifacts.inputs_path.read_text(encoding="utf-8").splitlines()
        return content_sha256(
            tuple(
                ModelInputItemV1.model_validate_json(line)
                for line in lines
                if line.strip()
            )
        )


def test_prepare_writes_four_dev_batches_and_no_gold(
    catalog: _Catalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(socket.socket, "connect", _no_sockets)
    output_dir = tmp_path / "dev-2026-09-20"

    assert _prepare(catalog.path, output_dir) == 0

    batches = {label: _batch(output_dir, label) for label in _LABELS}
    for label, batch in batches.items():
        assert condition_label(batch.output_contract, batch.retrieval) == label
        assert len(batch.prompts) == _DEV_ITEMS
        assert tuple(p.item_id for p in batch.prompts) == _DEV_ITEM_IDS
        assert {p.split for p in batch.prompts} == {"dev"}
        lexical = label in _LEXICAL_LABELS
        for prompt in batch.prompts:
            assert ("retrieved_fields" in _payload(prompt)) is lexical
    assert all(
        left.retrieved_fields == right.retrieved_fields
        for left, right in zip(
            batches["C2"].prompts, batches["C4"].prompts, strict=True
        )
    )
    assert not list(output_dir.rglob("evaluator_gold.json"))
    assert not list(output_dir.rglob("*.pcap"))
    files = _files(output_dir)
    assert sorted(files) == [
        "prepare.json",
        *(f"prepared/{label}.json" for label in _LABELS),
    ]
    produced = b"".join(files.values())
    # Both splits: a held-out leak is the graver failure of the two.
    for case in model_semantic_cases():
        assert case.case_id.encode("utf-8") not in produced
        assert case.reference_filter.encode("utf-8") not in produced
        assert case.mutation_filter.encode("utf-8") not in produced
    manifest = _manifest(output_dir)
    assert manifest.split == "dev"
    assert manifest.item_ids == _DEV_ITEM_IDS
    assert manifest.top_k == 16
    assert manifest.catalog.catalog_hash == catalog.catalog_hash
    for condition in manifest.conditions:
        digest = hashlib.sha256(files[condition.path]).hexdigest()
        assert (condition.sha256, condition.prompt_count) == (
            digest,
            _DEV_ITEMS,
        )


def test_prepare_records_a_platform_independent_input_digest(
    catalog: _Catalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_cwd = tmp_path / "cwd-one"
    second_cwd = tmp_path / "cwd-two"
    first_cwd.mkdir()
    second_cwd.mkdir()

    monkeypatch.chdir(first_cwd)
    assert _prepare(catalog.path, tmp_path / "one") == 0
    monkeypatch.chdir(second_cwd)
    assert _prepare(catalog.path, tmp_path / "two") == 0

    first = _manifest(tmp_path / "one")
    second = _manifest(tmp_path / "two")
    assert first.model_inputs_sha256 == second.model_inputs_sha256
    assert first.model_inputs_sha256 == _split_digest()


def test_prepare_reads_gzip_catalogs_to_identical_prompts(
    catalog: _Catalog, tmp_path: Path
) -> None:
    archive = tmp_path / "fixture.sqlite3.gz"
    with archive.open("xb") as stream:
        with gzip.GzipFile(
            filename="", fileobj=stream, mode="wb", mtime=0
        ) as compressed:
            compressed.write(catalog.path.read_bytes())

    assert _prepare(catalog.path, tmp_path / "plain") == 0
    assert _prepare(archive, tmp_path / "archive") == 0

    for label in _LABELS:
        plain = tmp_path / "plain" / "prepared" / f"{label}.json"
        packed = tmp_path / "archive" / "prepared" / f"{label}.json"
        assert plain.read_bytes() == packed.read_bytes()
    first = _manifest(tmp_path / "plain").catalog
    second = _manifest(tmp_path / "archive").catalog
    assert first.sqlite_sha256 == second.sqlite_sha256
    assert first.catalog_hash == second.catalog_hash
    assert first.file_sha256 != second.file_sha256
    assert (first.file_name, second.file_name) == (
        "fixture.sqlite3",
        "fixture.sqlite3.gz",
    )


def test_prepare_never_overwrites_and_never_retrieves_test_items(
    catalog: _Catalog,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    requested: list[str] = []
    wrapped = model_run.retrieve_fields

    def _record(
        path: Path,
        items: Sequence[FieldRetrievalItemV1],
        *,
        top_k: int = 16,
    ) -> tuple[FieldRetrievalResultV1, ...]:
        requested.extend(item.item_id for item in items)
        return wrapped(path, items, top_k=top_k)

    monkeypatch.setattr(model_run, "retrieve_fields", _record)
    output_dir = tmp_path / "dev-once"
    assert _prepare(catalog.path, output_dir) == 0
    assert tuple(requested) == _DEV_ITEM_IDS
    before = _files(output_dir)
    capsys.readouterr()

    assert _prepare(catalog.path, output_dir) == 2

    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "output_exists"
    assert _files(output_dir) == before
    assert not list(tmp_path.glob(".*.partial"))


def test_prepare_records_items_whose_context_is_empty(
    catalog: _Catalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = ("mei-0003", "mei-0007")
    field = RetrievedFieldV1(
        rank=1,
        abbreviation="ip.ttl",
        field_type=FieldType.INTEGER,
        protocol="ip",
        display_name="Time to Live",
    )

    def _fixed(
        path: Path,
        items: Sequence[FieldRetrievalItemV1],
        *,
        top_k: int = 16,
    ) -> tuple[FieldRetrievalResultV1, ...]:
        assert path.is_file() and top_k == 16
        return tuple(
            FieldRetrievalResultV1(
                item_id=item.item_id,
                fields=() if item.item_id in empty else (field,),
            )
            for item in items
        )

    monkeypatch.setattr(model_run, "retrieve_fields", _fixed)
    output_dir = tmp_path / "dev-empty"

    assert _prepare(catalog.path, output_dir) == 0

    assert _manifest(output_dir).empty_context_item_ids == empty
    for label in _LEXICAL_LABELS:
        batch = _batch(output_dir, label)
        assert len(batch.prompts) == _DEV_ITEMS
        blank = [
            prompt
            for prompt in batch.prompts
            if '"retrieved_fields":[]' in prompt.messages[1].content
        ]
        assert tuple(prompt.item_id for prompt in blank) == empty


def test_prepare_honours_a_shallower_retrieval_depth(
    catalog: _Catalog, tmp_path: Path
) -> None:
    output_dir = tmp_path / "dev-shallow"

    assert (
        model_run.main(
            [
                "prepare",
                "--catalog",
                str(catalog.path),
                "--output-dir",
                str(output_dir),
                "--source-revision",
                "test",
                "--top-k",
                "3",
            ]
        )
        == 0
    )

    assert _manifest(output_dir).top_k == 3
    for label in _LEXICAL_LABELS:
        prompts = _batch(output_dir, label).prompts
        depths = {len(prompt.retrieved_fields) for prompt in prompts}
        assert max(depths) == 3


@pytest.mark.parametrize(
    ("option", "value"),
    [("--top-k", "0"), ("--top-k", "33"), ("--source-revision", " ")],
)
def test_prepare_rejects_arguments_outside_their_bounds(
    catalog: _Catalog, tmp_path: Path, option: str, value: str
) -> None:
    output_dir = tmp_path / "dev-rejected"
    argv = [
        "prepare",
        "--catalog",
        str(catalog.path),
        "--output-dir",
        str(output_dir),
        "--source-revision",
        "test",
        option,
        value,
    ]

    with pytest.raises(SystemExit) as refusal:
        model_run.main(argv)

    assert refusal.value.code == 2
    assert not output_dir.exists()


def test_prepare_leaves_nothing_behind_when_retrieval_fails(
    catalog: _Catalog,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _fail(
        path: Path,
        items: Sequence[FieldRetrievalItemV1],
        *,
        top_k: int = 16,
    ) -> tuple[FieldRetrievalResultV1, ...]:
        assert path.is_file() and items and top_k == 16
        raise FieldRetrievalError(
            "catalog_unavailable", "Frozen field inventory is unavailable"
        )

    monkeypatch.setattr(model_run, "retrieve_fields", _fail)
    output_dir = tmp_path / "dev-broken"

    assert _prepare(catalog.path, output_dir) == 2

    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "catalog_unavailable"
    assert not output_dir.exists()
    assert list(tmp_path.iterdir()) == []


def test_prepare_fails_closed_on_a_stale_source_file(
    catalog: _Catalog,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        model_run,
        "_MODEL_SIDE_FILES",
        (
            "scripts/model_run.py",
            "src/dfilterforge/does_not_exist.py",
        ),
    )
    output_dir = tmp_path / "dev-stale"

    assert _prepare(catalog.path, output_dir) == 2

    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "source_file_missing"
    assert not output_dir.exists()
    assert list(tmp_path.iterdir()) == []


def test_prepare_rejects_an_unusable_output_name(
    catalog: _Catalog,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "Dev Prepare"

    assert _prepare(catalog.path, output_dir) == 2

    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "prepare_id_invalid"
    assert not output_dir.exists()
    assert list(tmp_path.iterdir()) == []


_API_KEY = "sk-test-SECRET-4d1a"
_MODEL_ID = "vendor/model-a"
_RUN_ID = "dev-fake-2026-09-20"
_OK_CONTENT = (
    '{"schema_version":"direct-filter/1.0","status":"ready",'
    '"display_filter":"tcp"}'
)
_ERROR_BODY = b'{"error":{"code":"provider_said_no"}}'
_PROVIDER_ERROR_BODY = json.dumps(
    {
        "id": "gen-error",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": ""},
                "finish_reason": "error",
                "error": {"code": 502},
            }
        ],
    }
).encode("utf-8")
_EMPTY_BODY = json.dumps(
    {
        "id": "gen-empty",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": None},
                "finish_reason": "length",
            }
        ],
    }
).encode("utf-8")


class _Received(NamedTuple):
    """One request the fake provider answered."""

    path: str
    authorization: str | None
    body: bytes


class _Provider(NamedTuple):
    """The fake endpoint's address and the requests it has been sent."""

    url: str
    received: list[_Received]


# Answers one scripted reply per request, keyed by the request ordinal.
_Script = Callable[[int], tuple[int, bytes]]


def _ok_body(**usage: object) -> bytes:
    """Returns one successful chat-completions reply body."""
    envelope: dict[str, Any] = {
        "id": "gen-ok",
        "model": _MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": _OK_CONTENT},
                "finish_reason": "stop",
            }
        ],
    }
    if usage:
        envelope["usage"] = usage
    return json.dumps(envelope).encode("utf-8")


_OK = _ok_body()
_METERED = _ok_body(completion_tokens=100)
_PRICED = _ok_body(cost=5e-06)
_OVERPRICED = _ok_body(cost=1500.0)
# One answer whose reasoning the endpoint neither hid nor switched off.
_REASONED = json.dumps(
    {
        "id": "gen-reasoned",
        "model": _MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": _OK_CONTENT,
                    "reasoning": "first, read the intent",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"completion_tokens_details": {"reasoning_tokens": 128}},
    }
).encode("utf-8")
# A scripted status that answers nothing at all and closes the socket.
_HANG_UP = 0


def _healthy(_ordinal: int) -> tuple[int, bytes]:
    """Answers every request with the same usable completion."""
    return 200, _OK


def _metered(_ordinal: int) -> tuple[int, bytes]:
    """Answers every request with a completion that reports its tokens."""
    return 200, _METERED


def _priced(_ordinal: int) -> tuple[int, bytes]:
    """Answers every request with the cost the provider charged for it."""
    return 200, _PRICED


def _dropped(ordinal: int) -> tuple[int, bytes]:
    """Hangs up on request three of the first pass, and answers the rest."""
    if ordinal == 3:
        return _HANG_UP, b""
    return 200, _OK


def _flaky(ordinal: int) -> tuple[int, bytes]:
    """Answers request three with 429 and request four with 400."""
    if ordinal == 3:
        return 429, _ERROR_BODY
    if ordinal == 4:
        return 400, _ERROR_BODY
    return 200, _OK


def _always_failing_third(ordinal: int) -> tuple[int, bytes]:
    """Answers 503 to one item on the first pass and on both resumes."""
    if ordinal in (3, _PASS_REQUESTS + 1, _PASS_REQUESTS + 2):
        return 503, _ERROR_BODY
    return 200, _OK


def _overpriced(ordinal: int) -> tuple[int, bytes]:
    """Reports a charge for request one that no run could have incurred."""
    if ordinal == 1:
        return 200, _OVERPRICED
    return 200, _OK


def _reasoned(_ordinal: int) -> tuple[int, bytes]:
    """Answers with reasoning the run asked the provider to switch off."""
    return 200, _REASONED


def _in_band(ordinal: int) -> tuple[int, bytes]:
    """Answers request one with a provider error and two with no content."""
    if ordinal == 1:
        return 200, _PROVIDER_ERROR_BODY
    if ordinal == 2:
        return 200, _EMPTY_BODY
    return 200, _OK


class _Switch:
    """Answers one fixed failing status until the test flips it to 200."""

    def __init__(self, status: int) -> None:
        """Starts out answering ``status`` to every request."""
        self.status = status

    def __call__(self, _ordinal: int) -> tuple[int, bytes]:
        """Answers the current status, with a body that suits it."""
        if self.status == 200:
            return 200, _OK
        return self.status, _ERROR_BODY


@contextmanager
def _provider(script: _Script) -> Generator[_Provider, None, None]:
    """Serves one scripted reply per request, in request order."""
    received: list[_Received] = []

    class Handler(BaseHTTPRequestHandler):

        def do_POST(self) -> None:  # pylint: disable=invalid-name
            length = int(self.headers.get("Content-Length") or 0)
            received.append(
                _Received(
                    self.path,
                    self.headers.get("Authorization"),
                    self.rfile.read(length),
                )
            )
            status, body = script(len(received))
            if status == _HANG_UP:
                self.close_connection = True
                return
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield _Provider(
            f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
            received,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _write_config(
    path: Path,
    url: str,
    *,
    settings: dict[str, Any] | None = None,
    prices: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Writes one user-local call configuration file."""
    document: dict[str, Any] = {
        "endpoint_url": url,
        "settings": {"model_id": _MODEL_ID, **(settings or {})},
        "prices": {
            "usd_per_million_input": 0.117,
            "usd_per_million_output": 0.455,
            "source": "fixture prices",
            **(prices or {}),
        },
        **(extra or {}),
    }
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")


def _call(
    prepare_dir: Path, config: Path, *extra: str, run_id: str = _RUN_ID
) -> int:
    """Runs one call pass with the arguments every call test shares."""
    return model_run.main(
        [
            "call",
            "--prepare-dir",
            str(prepare_dir),
            "--run-id",
            run_id,
            "--config",
            str(config),
            "--max-usd",
            "1",
            "--source-revision",
            "test",
            "--min-interval-seconds",
            "0",
            *extra,
        ]
    )


def _workspace(prepared: Path, tmp_path: Path) -> Path:
    """Returns a private copy of the shared prepared directory."""
    target = tmp_path / prepared.name
    shutil.copytree(prepared, target)
    return target


def _run_dir(prepare_dir: Path) -> Path:
    """Returns the run directory this module's calls all write into."""
    return prepare_dir / "runs" / _RUN_ID


def _run_manifest(prepare_dir: Path) -> RunManifestV1:
    """Reads the manifest the last call pass wrote."""
    text = (_run_dir(prepare_dir) / "run_manifest.json").read_text(
        encoding="utf-8"
    )
    return RunManifestV1.model_validate_json(text)


def _answers(prepare_dir: Path, label: str) -> CompletionBatchV1:
    """Reads one condition's published completion batch."""
    text = (_run_dir(prepare_dir) / "completions" / f"{label}.json").read_text(
        encoding="utf-8"
    )
    return CompletionBatchV1.model_validate_json(text)


def _no_gold(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("call must read neither gold nor the catalog")


@pytest.fixture(name="prepared", scope="module")
def fixture_prepared(
    catalog: _Catalog, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """Prepares one real dev prompt set for the call tests to answer."""
    output_dir = tmp_path_factory.mktemp("call") / "dev-call"
    assert _prepare(catalog.path, output_dir) == 0
    return output_dir


def test_call_sends_each_prompt_once_and_records_raw_batches(
    prepared: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One pass answers every prepared prompt exactly once."""
    monkeypatch.setenv(API_KEY_ENV, _API_KEY)
    monkeypatch.setattr(model_run, "generate_model_split", _no_gold)
    monkeypatch.setattr(model_run, "open_frozen_catalog", _no_gold)
    prepare_dir = _workspace(prepared, tmp_path)
    config = tmp_path / "call.json"

    with _provider(_healthy) as provider:
        _write_config(config, provider.url)
        assert _call(prepare_dir, config) == 0
        assert len(provider.received) == _PASS_REQUESTS
        assert {entry.authorization for entry in provider.received} == {
            f"Bearer {_API_KEY}"
        }

    run_dir = _run_dir(prepare_dir)
    assert sorted(_files(run_dir)) == [
        *(f"attempts/{label}.jsonl" for label in _LABELS),
        *(f"completions/{label}.json" for label in _LABELS),
        "prepare.json",
        *(f"prepared/{label}.json" for label in _LABELS),
        "run_manifest.json",
    ]
    source_files = _files(prepare_dir)
    for name in ("prepare.json", *(f"prepared/{x}.json" for x in _LABELS)):
        assert (run_dir / name).read_bytes() == source_files[name]
    for label in _LABELS:
        batch = _answers(prepare_dir, label)
        assert tuple(a.item_id for a in batch.completions) == _DEV_ITEM_IDS
        assert {a.status for a in batch.completions} == {
            CompletionStatusV1.COMPLETED
        }
    manifest = _run_manifest(prepare_dir)
    assert manifest.endpoint_host == "127.0.0.1"
    assert manifest.settings.model_id == _MODEL_ID
    assert manifest.prices is not None
    assert manifest.prices.usd_per_million_input == 0.117
    assert manifest.prices.usd_per_million_output == 0.455
    assert manifest.prices.source == "fixture prices"
    assert manifest.token_bound_rule == "utf8-bytes-plus-64"
    assert manifest.created_at.tzinfo is not None
    assert manifest.prepare.split == "dev"
    assert manifest.status == "complete"
    assert len(manifest.invocations) == 1
    invocation = manifest.invocations[0]
    assert invocation.source_revision == "test"
    assert invocation.stop_reason is None
    assert invocation.started_at <= invocation.finished_at
    for condition in manifest.conditions:
        assert set(condition.attempts.values()) == {1}
        assert (condition.completed, condition.pending) == (_DEV_ITEMS, 0)
    for data in _files(run_dir).values():
        assert _API_KEY.encode("utf-8") not in data
        assert provider.url.encode("utf-8") not in data


def test_budget_is_checked_before_every_request_and_resume_continues(
    prepared: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap bounds the whole run, and a resume finishes it."""
    monkeypatch.setenv(API_KEY_ENV, _API_KEY)
    prepare_dir = _workspace(prepared, tmp_path)
    config = tmp_path / "call.json"

    with _provider(_metered) as provider:
        _write_config(
            config,
            provider.url,
            settings={"max_output_tokens": 100},
            prices={
                "usd_per_million_input": 0.0,
                "usd_per_million_output": 500.0,
            },
        )
        assert _call(prepare_dir, config, "--max-usd", "0.125") == 1
        assert len(provider.received) == 2
        first = _run_manifest(prepare_dir)
        assert first.invocations[-1].stop_reason == "budget"
        assert first.charged_usd_upper_bound == 0.1
        assert not (_run_dir(prepare_dir) / "completions").exists()

        assert _call(prepare_dir, config, "--max-usd", "12", "--resume") == 0
        assert len(provider.received) == _PASS_REQUESTS

    second = _run_manifest(prepare_dir)
    assert second.status == "complete"
    assert len(second.invocations) == 2
    assert second.created_at == first.created_at
    counts = [
        count
        for condition in second.conditions
        for count in condition.attempts.values()
    ]
    assert len(counts) == _PASS_REQUESTS
    assert set(counts) == {1}


def test_resume_resends_only_transient_failures_and_keeps_every_attempt(
    prepared: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rate limit is re-sent; a rejected request is recorded as it is."""
    monkeypatch.setenv(API_KEY_ENV, _API_KEY)
    prepare_dir = _workspace(prepared, tmp_path)
    config = tmp_path / "call.json"

    with _provider(_flaky) as provider:
        _write_config(config, provider.url)
        assert _call(prepare_dir, config) == 1
        assert len(provider.received) == _PASS_REQUESTS
        assert _call(prepare_dir, config, "--resume") == 0
        assert len(provider.received) == _PASS_REQUESTS + 1

    log = (_run_dir(prepare_dir) / "attempts" / "C1.jsonl").read_text(
        encoding="utf-8"
    )
    # Every C1 item once, plus the rate-limited one again.
    assert len(log.splitlines()) == _DEV_ITEMS + 1
    conditions = _run_manifest(prepare_dir).conditions
    census = {condition.label: condition.attempts for condition in conditions}
    assert census["C1"]["mei-0003"] == 2
    assert census["C1"]["mei-0004"] == 1
    answers = {a.item_id: a for a in _answers(prepare_dir, "C1").completions}
    assert answers["mei-0003"].status is CompletionStatusV1.COMPLETED
    rejected = answers["mei-0004"]
    assert rejected.status is CompletionStatusV1.FAILED
    assert (rejected.error_code, rejected.http_status) == ("http_error", 400)


def test_transient_failures_are_abandoned_after_three_attempts(
    prepared: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The protocol's three-attempt ceiling is what stops a retry loop."""
    monkeypatch.setenv(API_KEY_ENV, _API_KEY)
    prepare_dir = _workspace(prepared, tmp_path)
    config = tmp_path / "call.json"

    with _provider(_always_failing_third) as provider:
        _write_config(config, provider.url)
        assert _call(prepare_dir, config) == 1
        assert _call(prepare_dir, config, "--resume") == 1
        assert _call(prepare_dir, config, "--resume") == 0
        assert len(provider.received) == _PASS_REQUESTS + 2
        assert _call(prepare_dir, config, "--resume") == 0
        assert len(provider.received) == _PASS_REQUESTS + 2

    manifest = _run_manifest(prepare_dir)
    assert manifest.status == "complete"
    conditions = {c.label: c for c in manifest.conditions}
    assert conditions["C1"].attempts["mei-0003"] == 3
    assert (conditions["C1"].failed, conditions["C1"].pending) == (1, 0)
    for condition in manifest.conditions:
        total = condition.completed + condition.failed + condition.pending
        assert total == _DEV_ITEMS
    answers = {a.item_id: a for a in _answers(prepare_dir, "C1").completions}
    assert answers["mei-0003"].status is CompletionStatusV1.FAILED
    assert answers["mei-0003"].http_status == 503


def test_fatal_http_status_stops_the_run_before_more_spend(
    prepared: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused credential ends the pass on its first request."""
    monkeypatch.setenv(API_KEY_ENV, _API_KEY)
    prepare_dir = _workspace(prepared, tmp_path)
    config = tmp_path / "call.json"
    switch = _Switch(401)

    with _provider(switch) as provider:
        _write_config(config, provider.url)
        assert _call(prepare_dir, config) == 1
        assert len(provider.received) == 1
        stopped = _run_manifest(prepare_dir)
        assert stopped.invocations[-1].stop_reason == "fatal_http"
        assert stopped.status == "incomplete"

        switch.status = 200
        assert _call(prepare_dir, config, "--resume") == 0
        assert len(provider.received) == _PASS_REQUESTS + 1
        assert provider.received[1].body == provider.received[0].body

    manifest = _run_manifest(prepare_dir)
    assert manifest.status == "complete"
    census = {c.label: c.attempts for c in manifest.conditions}
    assert census["C1"]["mei-0001"] == 2


def test_provider_faults_inside_http_200_are_final(
    prepared: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An in-band fault is an answer to record, not a request to repeat."""
    monkeypatch.setenv(API_KEY_ENV, _API_KEY)
    prepare_dir = _workspace(prepared, tmp_path)
    config = tmp_path / "call.json"

    with _provider(_in_band) as provider:
        _write_config(config, provider.url)
        assert _call(prepare_dir, config) == 0
        assert len(provider.received) == _PASS_REQUESTS
        assert _call(prepare_dir, config, "--resume") == 0
        assert len(provider.received) == _PASS_REQUESTS

    manifest = _run_manifest(prepare_dir)
    assert manifest.status == "complete"
    answers = {a.item_id: a for a in _answers(prepare_dir, "C1").completions}
    for item_id, code in (
        ("mei-0001", "provider_error"),
        ("mei-0002", "empty_content"),
    ):
        assert answers[item_id].status is CompletionStatusV1.FAILED
        assert answers[item_id].error_code == code
        assert answers[item_id].http_status == 200


def test_the_run_is_anchored_before_its_first_request(
    prepared: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file a resume needs exists from before the first request."""
    monkeypatch.setenv(API_KEY_ENV, _API_KEY)
    prepare_dir = _workspace(prepared, tmp_path)
    config = tmp_path / "call.json"
    anchors: list[str] = []

    def _watch(_ordinal: int) -> tuple[int, bytes]:
        path = _run_dir(prepare_dir) / "run_manifest.json"
        anchors.append(
            path.read_text(encoding="utf-8") if path.is_file() else ""
        )
        return 200, _OK

    with _provider(_watch) as provider:
        _write_config(config, provider.url)
        assert _call(prepare_dir, config) == 0
        assert len(provider.received) == _PASS_REQUESTS

    assert len(anchors) == _PASS_REQUESTS
    assert all(anchors)
    anchor = RunManifestV1.model_validate_json(anchors[0])
    assert anchor.status == "incomplete"
    assert len(anchor.invocations) == 1
    assert anchor.invocations[0].requests_sent == 0
    assert anchor.invocations[0].finished_at == anchor.invocations[0].started_at
    assert [condition.pending for condition in anchor.conditions] == [
        _DEV_ITEMS
    ] * 4
    assert _run_manifest(prepare_dir).status == "complete"


def test_a_pass_that_dies_before_recording_is_resumed_not_repeated(
    prepared: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Paid answers are never stranded by a pass that ends abruptly."""
    monkeypatch.setenv(API_KEY_ENV, _API_KEY)
    prepare_dir = _workspace(prepared, tmp_path)
    config = tmp_path / "call.json"

    def _died(*_args: object, **_kwargs: object) -> tuple[str, str]:
        raise RuntimeError("the pass died before it recorded its answers")

    with _provider(_healthy) as provider:
        _write_config(config, provider.url)
        monkeypatch.setattr(model_run, "_write_completions", _died)
        with pytest.raises(RuntimeError):
            _call(prepare_dir, config)
        assert len(provider.received) == _PASS_REQUESTS

        monkeypatch.undo()
        monkeypatch.setenv(API_KEY_ENV, _API_KEY)
        assert _call(prepare_dir, config, "--resume") == 0
        assert len(provider.received) == _PASS_REQUESTS

    manifest = _run_manifest(prepare_dir)
    assert manifest.status == "complete"
    assert len(manifest.invocations) == 2
    for condition in manifest.conditions:
        assert set(condition.attempts.values()) == {1}


def test_an_impossible_provider_charge_cannot_strand_a_paid_run(
    prepared: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One absurd money figure is a recorded failure, not a lost run."""
    monkeypatch.setenv(API_KEY_ENV, _API_KEY)
    prepare_dir = _workspace(prepared, tmp_path)
    config = tmp_path / "call.json"

    with _provider(_overpriced) as provider:
        _write_config(config, provider.url)
        assert _call(prepare_dir, config) == 0
        assert len(provider.received) == _PASS_REQUESTS

    manifest = _run_manifest(prepare_dir)
    assert manifest.status == "complete"
    assert manifest.charged_usd_upper_bound <= 1000
    answers = {a.item_id: a for a in _answers(prepare_dir, "C1").completions}
    refused = answers["mei-0001"]
    assert refused.status is CompletionStatusV1.FAILED
    assert (refused.error_code, refused.cost_usd) == ("client_error", None)


def test_the_first_answer_gates_a_run_that_kept_on_thinking(
    prepared: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One request, not sixty-four, is what an ignored control costs."""
    monkeypatch.setenv(API_KEY_ENV, _API_KEY)
    prepare_dir = _workspace(prepared, tmp_path)
    config = tmp_path / "call.json"

    with _provider(_reasoned) as provider:
        _write_config(config, provider.url)
        assert _call(prepare_dir, config) == 1
        assert len(provider.received) == 1
        gated = _run_manifest(prepare_dir)
        assert gated.status == "incomplete"
        assert gated.invocations[-1].stop_reason == "thinking_not_honoured"
        assert gated.invocations[-1].requests_sent == 1

        assert _call(prepare_dir, config, "--resume", "--no-gate-first") == 0
        assert len(provider.received) == _PASS_REQUESTS

    manifest = _run_manifest(prepare_dir)
    assert manifest.status == "complete"
    assert manifest.invocations[-1].stop_reason is None
    answers = {a.item_id: a for a in _answers(prepare_dir, "C1").completions}
    assert answers["mei-0001"].reasoning_tokens == 128


def test_call_refuses_a_test_split_prompt_set_before_any_request(
    prepared: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No held-out prompt set can reach a model before the freeze commit."""
    monkeypatch.setenv(API_KEY_ENV, _API_KEY)
    prepare_dir = _workspace(prepared, tmp_path)
    path = prepare_dir / "prepare.json"
    document = cast(dict[str, Any], json.loads(path.read_text("utf-8")))
    document["split"] = "test"
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
    config = tmp_path / "call.json"

    with _provider(_healthy) as provider:
        _write_config(config, provider.url)
        capsys.readouterr()
        refused = _call(prepare_dir, config, run_id="test-fake-2026-09-20")
        assert provider.received == []

    assert refused == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "prepare_invalid"


class _Bench(NamedTuple):
    """One prepared copy, its configuration and the fake provider."""

    prepare_dir: Path
    config: Path
    provider: _Provider
    monkeypatch: pytest.MonkeyPatch


def _rewrite_condition(
    prepare_dir: Path, label: str, document: dict[str, Any]
) -> None:
    """Rewrites one prepared file and records its new digest."""
    text = json.dumps(document)
    path = prepare_dir / "prepared" / f"{label}.json"
    path.write_text(text, encoding="utf-8", newline="\n")
    manifest_path = prepare_dir / "prepare.json"
    manifest = cast(
        dict[str, Any], json.loads(manifest_path.read_text("utf-8"))
    )
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    for condition in cast(list[dict[str, Any]], manifest["conditions"]):
        if condition["label"] == label:
            condition["sha256"] = digest
    manifest_path.write_text(
        json.dumps(manifest), encoding="utf-8", newline="\n"
    )


def _seed_run(bench: _Bench) -> None:
    """Creates a run directory without sending a single request."""
    assert _call(bench.prepare_dir, bench.config, "--max-usd", "0.0000001") == 1
    assert bench.provider.received == []


def _changed_settings(bench: _Bench) -> tuple[str, ...]:
    """Resumes a run whose recorded request settings no longer match."""
    _seed_run(bench)
    _write_config(
        bench.config, bench.provider.url, settings={"temperature": 0.5}
    )
    return ("--resume",)


def _held_out_prompt(bench: _Bench) -> tuple[str, ...]:
    """Rewrites one prompt as held-out and re-records its digest."""
    path = bench.prepare_dir / "prepared" / "C1.json"
    document = cast(dict[str, Any], json.loads(path.read_text("utf-8")))
    prompts = cast(list[dict[str, Any]], document["prompts"])
    prompts[0]["split"] = "test"
    _rewrite_condition(bench.prepare_dir, "C1", document)
    return ()


def _stale_source(bench: _Bench) -> tuple[str, ...]:
    """Records a model-side digest that no longer matches the file."""
    path = bench.prepare_dir / "prepare.json"
    manifest = cast(dict[str, Any], json.loads(path.read_text("utf-8")))
    cast(dict[str, str], manifest["source_files"])["scripts/model_run.py"] = (
        "0" * 64
    )
    path.write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    return ()


def _edited_prompt(bench: _Bench) -> tuple[str, ...]:
    """Edits a prepared file without recording the new digest."""
    path = bench.prepare_dir / "prepared" / "C2.json"
    path.write_bytes(path.read_bytes() + b" ")
    return ()


def _edited_copy(bench: _Bench) -> tuple[str, ...]:
    """Edits the run directory's own copy of a prompt file."""
    _seed_run(bench)
    path = _run_dir(bench.prepare_dir) / "prepared" / "C2.json"
    path.write_bytes(path.read_bytes() + b" ")
    return ("--resume",)


def _missing_key(bench: _Bench) -> tuple[str, ...]:
    """Removes the credential the call step requires."""
    bench.monkeypatch.delenv(API_KEY_ENV, raising=False)
    return ()


def _existing_run(bench: _Bench) -> tuple[str, ...]:
    """Leaves a run directory in the way of a fresh pass."""
    _run_dir(bench.prepare_dir).mkdir(parents=True)
    return ()


def _over_budget(bench: _Bench) -> tuple[str, ...]:
    """Asks for more than the project's own spending cap."""
    del bench
    return ("--max-usd", "13")


def _over_attempts(bench: _Bench) -> tuple[str, ...]:
    """Asks for more attempts than the protocol allows."""
    del bench
    return ("--max-attempts", "5")


def _unknown_config_key(bench: _Bench) -> tuple[str, ...]:
    """Writes a configuration carrying a key the contract forbids."""
    _write_config(
        bench.config, bench.provider.url, extra={"api_key": "sk-not-here"}
    )
    return ()


def _remote_plain_http(bench: _Bench) -> tuple[str, ...]:
    """Points the run at plain http on a host that is not local."""
    _write_config(bench.config, "http://example.invalid/v1/chat/completions")
    return ()


def _bad_run_id(bench: _Bench) -> tuple[str, ...]:
    """Names a run directory that is not a usable result name."""
    del bench
    return ("--run-id", "dev-bad")


def _foreign_split(bench: _Bench) -> tuple[str, ...]:
    """Names a run of one split over the prompt set of another."""
    del bench
    return ("--run-id", "test-fake-2026-09-20")


def _slow_interval(bench: _Bench) -> tuple[str, ...]:
    """Asks for a pace slower than the bound the run records."""
    del bench
    return ("--min-interval-seconds", "61")


def _no_run_to_resume(bench: _Bench) -> tuple[str, ...]:
    """Resumes a run that was never started."""
    del bench
    return ("--resume",)


def _broken_run_manifest(bench: _Bench) -> tuple[str, ...]:
    """Resumes a run whose manifest no longer parses."""
    _seed_run(bench)
    path = _run_dir(bench.prepare_dir) / "run_manifest.json"
    path.write_bytes(b"{}")
    return ("--resume",)


def _missing_run_manifest(bench: _Bench) -> tuple[str, ...]:
    """Resumes a run whose manifest is not there at all."""
    _seed_run(bench)
    (_run_dir(bench.prepare_dir) / "run_manifest.json").unlink()
    return ("--resume",)


def _missing_prepare(bench: _Bench) -> tuple[str, ...]:
    """Points the run at a directory that holds no prepare manifest."""
    (bench.prepare_dir / "prepare.json").unlink()
    return ()


def _missing_prompt_file(bench: _Bench) -> tuple[str, ...]:
    """Removes a prompt file the prepare manifest still records."""
    (bench.prepare_dir / "prepared" / "C3.json").unlink()
    return ()


def _missing_config(bench: _Bench) -> tuple[str, ...]:
    """Names a call configuration file that was never written."""
    bench.config.unlink()
    return ()


def _free_prices(bench: _Bench) -> tuple[str, ...]:
    """Prices every token at nothing, which disables the spend cap."""
    _write_config(
        bench.config,
        bench.provider.url,
        prices={
            "usd_per_million_input": 0.0,
            "usd_per_million_output": 0.0,
        },
    )
    return ()


def _unparsable_prompt(bench: _Bench) -> tuple[str, ...]:
    """Records a prepared file that is no longer a prompt batch."""
    _rewrite_condition(bench.prepare_dir, "C1", {"not": "a batch"})
    return ()


def _swapped_condition(bench: _Bench) -> tuple[str, ...]:
    """Files one condition's prompts under another condition's name."""
    source = bench.prepare_dir / "prepared" / "C3.json"
    document = cast(dict[str, Any], json.loads(source.read_text("utf-8")))
    _rewrite_condition(bench.prepare_dir, "C1", document)
    return ()


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (_changed_settings, "settings_changed"),
        (_held_out_prompt, "split_refused"),
        (_stale_source, "prepare_code_mismatch"),
        (_edited_prompt, "prepare_hash_mismatch"),
        (_edited_copy, "prepare_hash_mismatch"),
        (_missing_key, "api_key_missing"),
        (_existing_run, "run_exists"),
        (_over_budget, "budget_invalid"),
        (_over_attempts, "max_attempts_invalid"),
        (_unknown_config_key, "config_invalid"),
        (_remote_plain_http, "endpoint_invalid"),
        (_bad_run_id, "run_id_invalid"),
        (_foreign_split, "split_mismatch"),
        (_slow_interval, "interval_invalid"),
        (_no_run_to_resume, "run_missing"),
        (_broken_run_manifest, "run_manifest_invalid"),
        (_missing_run_manifest, "run_manifest_invalid"),
        (_missing_prepare, "prepare_invalid"),
        (_missing_prompt_file, "prepare_hash_mismatch"),
        (_missing_config, "config_invalid"),
        (_free_prices, "config_invalid"),
        (_unparsable_prompt, "prepare_invalid"),
        (_swapped_condition, "condition_mismatch"),
    ],
)
def test_call_refuses_before_any_request(
    prepared: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mutate: Callable[[_Bench], Sequence[str]],
    code: str,
) -> None:
    """Every refusal lands before the pass sends anything at all."""
    monkeypatch.setenv(API_KEY_ENV, _API_KEY)
    prepare_dir = _workspace(prepared, tmp_path)
    config = tmp_path / "call.json"

    with _provider(_healthy) as provider:
        _write_config(config, provider.url)
        extra = mutate(_Bench(prepare_dir, config, provider, monkeypatch))
        capsys.readouterr()
        refused = _call(prepare_dir, config, *extra)
        assert provider.received == []

    assert refused == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == code


def test_torn_attempt_log_stops_a_resume(
    prepared: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A log that ends mid-line is never guessed at."""
    monkeypatch.setenv(API_KEY_ENV, _API_KEY)
    prepare_dir = _workspace(prepared, tmp_path)
    config = tmp_path / "call.json"

    with _provider(_metered) as provider:
        _write_config(
            config,
            provider.url,
            settings={"max_output_tokens": 100},
            prices={
                "usd_per_million_input": 0.0,
                "usd_per_million_output": 1000.0,
            },
        )
        assert _call(prepare_dir, config, "--max-usd", "0.25") == 1
        assert len(provider.received) == 2
        log = _run_dir(prepare_dir) / "attempts" / "C1.jsonl"
        log.write_bytes(log.read_bytes()[:-40])
        capsys.readouterr()

        refused = _call(prepare_dir, config, "--max-usd", "12", "--resume")
        assert provider.received == provider.received[:2]

    assert refused == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "attempt_log_invalid"


def test_pacing_spaces_request_starts(
    prepared: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every request but the first waits out the configured interval."""
    monkeypatch.setenv(API_KEY_ENV, _API_KEY)
    prepare_dir = _workspace(prepared, tmp_path)
    config = tmp_path / "call.json"
    ticks = itertools.count(1)
    sleeps: list[tuple[float, int]] = []

    with _provider(_healthy) as provider:
        _write_config(config, provider.url)

        def _clock() -> float:
            return next(ticks) / 10

        def _record(seconds: float) -> None:
            sleeps.append((seconds, len(provider.received)))

        monkeypatch.setattr(model_run, "_monotonic", _clock)
        monkeypatch.setattr(model_run, "_sleep", _record)
        sent = _call(prepare_dir, config, "--min-interval-seconds", "1.0")
        assert len(provider.received) == _PASS_REQUESTS

    assert sent == 0
    assert len(sleeps) == _PASS_REQUESTS - 1
    assert all(0 < seconds <= 1.0 for seconds, _ in sleeps)
    assert min(answered for _, answered in sleeps) >= 1


def test_a_reported_cost_is_what_the_run_is_charged(
    prepared: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider-reported charge outranks every price-derived bound."""
    monkeypatch.setenv(API_KEY_ENV, _API_KEY)
    prepare_dir = _workspace(prepared, tmp_path)
    config = tmp_path / "call.json"

    with _provider(_priced) as provider:
        _write_config(config, provider.url)
        assert _call(prepare_dir, config) == 0
        assert len(provider.received) == _PASS_REQUESTS

    manifest = _run_manifest(prepare_dir)
    # Each reply reports a charge of 5 micro-USD.
    assert manifest.charged_usd_upper_bound == _PASS_REQUESTS * 5 / 1e6
    assert manifest.provider_reported_usd == _PASS_REQUESTS * 5 / 1e6


def test_a_dropped_connection_is_retried_and_charged_in_full(
    prepared: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lost answer may already have been generated, so it costs its bound."""
    monkeypatch.setenv(API_KEY_ENV, _API_KEY)
    prepare_dir = _workspace(prepared, tmp_path)
    config = tmp_path / "call.json"

    with _provider(_dropped) as provider:
        _write_config(config, provider.url)
        assert _call(prepare_dir, config) == 1
        assert len(provider.received) == _PASS_REQUESTS
        assert _call(prepare_dir, config, "--resume") == 0
        assert len(provider.received) == _PASS_REQUESTS + 1

    log = (_run_dir(prepare_dir) / "attempts" / "C1.jsonl").read_text(
        encoding="utf-8"
    )
    attempts = [json.loads(line) for line in log.splitlines()]
    dropped = [
        attempt
        for attempt in attempts
        if attempt["completion"]["item_id"] == "mei-0003"
    ]
    assert len(dropped) == 2
    assert dropped[0]["completion"]["error_code"] == "transport_error"
    assert dropped[0]["completion"]["http_status"] is None
    assert dropped[0]["charged_micro_usd"] > 0
    answers = {a.item_id: a for a in _answers(prepare_dir, "C1").completions}
    assert answers["mei-0003"].status is CompletionStatusV1.COMPLETED


_PUBLISH_RUN_ID = "dev-qwen3-32b-2026-09-20"
_PUBLISHED_FILES: tuple[str, ...] = getattr(model_run, "_PUBLISHED_FILES")
# One credential-shaped token that is not this fixture's own key.
_BEARER = "Bearer " + "b" * 32


class _CompleteRun(NamedTuple):
    """One finished run directory and the endpoint that answered it."""

    run_dir: Path
    endpoint_url: str


class _Publishable(NamedTuple):
    """What one publish refusal may act on before the command runs."""

    run_dir: Path
    output: Path
    incomplete: Path


def _publish(run_dir: Path, output: Path) -> int:
    """Publishes one run directory into a committed results directory."""
    return model_run.main(
        ["publish", "--run-dir", str(run_dir), "--output", str(output)]
    )


def _run_copy(source: Path, tmp_path: Path) -> Path:
    """Returns a private copy of a finished run directory."""
    target = tmp_path / "runs" / source.name
    shutil.copytree(source, target)
    return target


def _edit_manifest(
    run_dir: Path, change: Callable[[dict[str, Any]], None]
) -> None:
    """Rewrites the run manifest after one deliberate change."""
    path = run_dir / "run_manifest.json"
    document = cast(dict[str, Any], json.loads(path.read_text("utf-8")))
    change(document)
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")


def _rewrite_run_file(run_dir: Path, name: str, data: bytes) -> None:
    """Rewrites one run file and records its new digest in the manifest."""
    (run_dir / name).write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    label = Path(name).stem
    field = (
        "attempts_sha256" if name.endswith(".jsonl") else "completions_sha256"
    )

    def _record(document: dict[str, Any]) -> None:
        for condition in cast(list[dict[str, Any]], document["conditions"]):
            if condition["label"] == label:
                condition[field] = digest

    _edit_manifest(run_dir, _record)


def _freeze_prompts(run_dir: Path, output: Path) -> None:
    """Commits the prompt set, its receipt and both control scores.

    The receipt is committed at the run root, where the offline scorer
    reads it: ``prepared/`` holds the four condition files and nothing
    else, so a receipt left there would make the committed directory
    unscorable.
    """
    (output / "prepared").mkdir(parents=True)
    for label in _LABELS:
        shutil.copy2(
            run_dir / "prepared" / f"{label}.json",
            output / "prepared" / f"{label}.json",
        )
    shutil.copy2(run_dir / "prepare.json", output / "prepare.json")
    for control in ("control-reference", "control-mutation"):
        (output / control).mkdir()
        (output / control / "summary.json").write_bytes(b"{}\n")


@pytest.fixture(name="complete_run", scope="module")
def fixture_complete_run(
    prepared: Path, tmp_path_factory: pytest.TempPathFactory
) -> _CompleteRun:
    """Answers one prepared dev prompt set in full, ready to publish."""
    root = tmp_path_factory.mktemp("publish")
    workspace = root / "dev-publish"
    shutil.copytree(prepared, workspace)
    config = root / "call.json"
    patch = pytest.MonkeyPatch()
    patch.setenv(API_KEY_ENV, _API_KEY)
    try:
        with _provider(_healthy) as provider:
            _write_config(config, provider.url)
            assert _call(workspace, config, run_id=_PUBLISH_RUN_ID) == 0
            assert len(provider.received) == _PASS_REQUESTS
            endpoint = provider.url
    finally:
        patch.undo()
    return _CompleteRun(workspace / "runs" / _PUBLISH_RUN_ID, endpoint)


@pytest.fixture(name="incomplete_run", scope="module")
def fixture_incomplete_run(
    prepared: Path, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """Stops one pass on its budget before it sends a single request."""
    root = tmp_path_factory.mktemp("stopped")
    workspace = root / "dev-stopped"
    shutil.copytree(prepared, workspace)
    config = root / "call.json"
    patch = pytest.MonkeyPatch()
    patch.setenv(API_KEY_ENV, _API_KEY)
    try:
        with _provider(_healthy) as provider:
            _write_config(config, provider.url)
            stopped = _call(
                workspace,
                config,
                "--max-usd",
                "0.0000001",
                run_id=_PUBLISH_RUN_ID,
            )
            assert (stopped, provider.received) == (1, [])
    finally:
        patch.undo()
    return workspace / "runs" / _PUBLISH_RUN_ID


def test_publish_copies_a_complete_run_verbatim(
    complete_run: _CompleteRun,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A published directory is the run, byte for byte, and nothing else."""
    monkeypatch.setattr(socket.socket, "connect", _no_sockets)
    run_dir = _run_copy(complete_run.run_dir, tmp_path)
    output = tmp_path / "docs" / "results" / _PUBLISH_RUN_ID
    capsys.readouterr()

    assert _publish(run_dir, output) == 0

    published = _files(output)
    source = _files(run_dir)
    assert sorted(published) == sorted(_PUBLISHED_FILES)
    assert all(published[name] == source[name] for name in _PUBLISHED_FILES)
    produced = b"".join(published.values())
    for absent in (complete_run.endpoint_url, "call.json", "runs/", _API_KEY):
        assert absent.encode("utf-8") not in produced
    manifest = RunManifestV1.model_validate_json(published["run_manifest.json"])
    assert manifest.prepare.catalog.catalog_hash
    assert (
        manifest.prepare_sha256
        == hashlib.sha256(published["prepare.json"]).hexdigest()
    )
    report = cast(dict[str, Any], json.loads(capsys.readouterr().out))
    assert report["run_id"] == _PUBLISH_RUN_ID
    assert report["files"] == list(_PUBLISHED_FILES)
    assert not list(output.parent.glob(".*.partial"))


def test_published_manifest_round_trips_through_the_scorer_reader(
    complete_run: _CompleteRun, tmp_path: Path
) -> None:
    """The scorer reads a published directory with no key and no network."""
    run_dir = _run_copy(complete_run.run_dir, tmp_path)
    output = tmp_path / "docs" / "results" / _PUBLISH_RUN_ID
    assert _publish(run_dir, output) == 0

    loaded = load_run(output)

    manifest = loaded.manifest
    assert manifest is not None and loaded.prepare is not None
    check_prepare(loaded.prepare, loaded.prepared)
    check_manifest(manifest, loaded.prepared, loaded.completions)
    assert check_splits(loaded.prepared, manifest, loaded.prepare) == "dev"
    assert manifest.prepare.split == "dev"
    prices = manifest.prices
    assert prices is not None
    assert prices.usd_per_million_input > 0
    assert prices.usd_per_million_output > 0
    assert prices.source
    assert manifest.created_at.tzinfo is not None
    assert manifest.max_attempts <= 3
    assert sorted({run.label: run for run in manifest.conditions}) == list(
        _LABELS
    )


def test_publish_merges_with_prompts_committed_ahead_of_the_run(
    complete_run: _CompleteRun,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A results directory frozen before the run is extended, not replaced."""
    run_dir = _run_copy(complete_run.run_dir, tmp_path)
    output = tmp_path / "first" / _PUBLISH_RUN_ID
    _freeze_prompts(run_dir, output)
    frozen = _files(output)

    assert _publish(run_dir, output) == 0

    published = _files(output)
    assert sorted(published) == sorted(
        {
            *_PUBLISHED_FILES,
            "control-reference/summary.json",
            "control-mutation/summary.json",
        }
    )
    assert all(published[name] == data for name, data in frozen.items())
    assert published["prepare.json"] == frozen["prepare.json"]
    # The frozen-ahead layout is the one the offline scorer reads: the
    # receipt sits at the run root, because prepared/ may hold nothing
    # but the four condition files.
    assert load_run(output).prepare is not None

    drifted = tmp_path / "second" / _PUBLISH_RUN_ID
    _freeze_prompts(run_dir, drifted)
    stale = drifted / "prepared" / "C2.json"
    stale.write_bytes(stale.read_bytes() + b" ")
    before = _files(drifted)
    capsys.readouterr()

    refused = _publish(run_dir, drifted)

    assert refused == 2
    error = cast(dict[str, Any], json.loads(capsys.readouterr().err))
    assert error["error"]["code"] == "prepared_drift"
    assert _files(drifted) == before
    assert not list(drifted.parent.glob(".*.partial"))


def _stopped_run(target: _Publishable) -> tuple[Path, Path]:
    """Publishes a pass that stopped on its budget with nothing answered."""
    return target.incomplete, target.output


def _no_prices(target: _Publishable) -> tuple[Path, Path]:
    """Removes the token prices the cost column is derived from."""
    _edit_manifest(target.run_dir, lambda document: document.pop("prices"))
    return target.run_dir, target.output


def _too_many_attempts(target: _Publishable) -> tuple[Path, Path]:
    """Claims more attempts per item than the published protocol allows."""
    _edit_manifest(
        target.run_dir, lambda document: document.update(max_attempts=4)
    )
    return target.run_dir, target.output


def _short_run_id(target: _Publishable) -> tuple[Path, Path]:
    """Names the run something that is not a dated result directory."""
    _edit_manifest(
        target.run_dir, lambda document: document.update(run_id="dev-run")
    )
    return target.run_dir, target.output


def _renamed_output(target: _Publishable) -> tuple[Path, Path]:
    """Publishes into a directory named after some other run."""
    return target.run_dir, target.output.parent / "dev-other-2026-09-20"


def _stale_answers(target: _Publishable) -> tuple[Path, Path]:
    """Leaves a previous publication's completions at the target."""
    path = target.output / "completions" / "C1.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"{}\n")
    return target.run_dir, target.output


def _stale_score(target: _Publishable) -> tuple[Path, Path]:
    """Leaves a score of a previous run at the target."""
    path = target.output / "scored" / "summary.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"{}\n")
    return target.run_dir, target.output


def _edited_answers(target: _Publishable) -> tuple[Path, Path]:
    """Changes one recorded answer without re-recording its digest."""
    path = target.run_dir / "completions" / "C3.json"
    path.write_bytes(path.read_bytes() + b" ")
    return target.run_dir, target.output


def _edited_receipt(target: _Publishable) -> tuple[Path, Path]:
    """Changes the preparation receipt the manifest recorded a digest of."""
    path = target.run_dir / "prepare.json"
    path.write_bytes(path.read_bytes() + b" ")
    return target.run_dir, target.output


def _foreign_receipt(target: _Publishable) -> tuple[Path, Path]:
    """Commits a receipt from another preparation of the same prompts.

    Prompt bytes carry no preparation identity, so re-preparing yields
    the same four files under a receipt naming another ``prepare_id``.
    """
    _freeze_prompts(target.run_dir, target.output)
    path = target.output / "prepare.json"
    document = cast(dict[str, Any], json.loads(path.read_text("utf-8")))
    document["prepare_id"] = "dev-2026-09-19-other"
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
    return target.run_dir, target.output


def _torn_attempt_log(target: _Publishable) -> tuple[Path, Path]:
    """Cuts the last attempt line in half and records the new digest."""
    log = (target.run_dir / "attempts" / "C1.jsonl").read_bytes()
    _rewrite_run_file(target.run_dir, "attempts/C1.jsonl", log[:-40])
    return target.run_dir, target.output


def _plant_in_an_attempt(run_dir: Path, secret: str) -> None:
    """Writes one secret into the last attempt line and re-records it."""
    lines = (run_dir / "attempts" / "C1.jsonl").read_text("utf-8").splitlines()
    record = cast(dict[str, Any], json.loads(lines[-1]))
    completion = cast(dict[str, Any], record["completion"])
    completion["response_text"] = f"{completion['response_text']} {secret}"
    lines[-1] = json.dumps(record)
    data = ("\n".join(lines) + "\n").encode("utf-8")
    _rewrite_run_file(run_dir, "attempts/C1.jsonl", data)


def _key_in_an_attempt(target: _Publishable) -> tuple[Path, Path]:
    """Writes the credential into an attempt log and re-records it."""
    _plant_in_an_attempt(target.run_dir, _API_KEY)
    return target.run_dir, target.output


def _missing_answer_file(target: _Publishable) -> tuple[Path, Path]:
    """Publishes a run one condition's recorded answers are missing from."""
    (target.run_dir / "completions" / "C4.json").unlink()
    return target.run_dir, target.output


def _file_at_the_output(target: _Publishable) -> tuple[Path, Path]:
    """Publishes over something at the target that is not a directory."""
    target.output.write_bytes(b"{}\n")
    return target.run_dir, target.output


def _token_in_an_answer(target: _Publishable) -> tuple[Path, Path]:
    """Leaves a credential-shaped token inside one recorded answer."""
    path = target.run_dir / "completions" / "C1.json"
    document = cast(dict[str, Any], json.loads(path.read_text("utf-8")))
    answers = cast(list[dict[str, Any]], document["completions"])
    answers[0]["response_text"] = f"{answers[0]['response_text']} {_BEARER}"
    data = (json.dumps(document) + "\n").encode("utf-8")
    _rewrite_run_file(target.run_dir, "completions/C1.json", data)
    return target.run_dir, target.output


def _linked_prompt_directory(target: _Publishable) -> tuple[Path, Path]:
    """Points the committed prompt directory outside the results tree."""
    if sys.platform != "linux":
        pytest.skip("symbolic links need a POSIX file system")
    elsewhere = target.output.parent / "elsewhere"
    elsewhere.mkdir(parents=True)
    target.output.mkdir()
    (target.output / "prepared").symlink_to(elsewhere)
    return target.run_dir, target.output


def _linked_answers(target: _Publishable) -> tuple[Path, Path]:
    """Replaces one recorded answer file with a symbolic link."""
    if sys.platform != "linux":
        pytest.skip("symbolic links need a POSIX file system")
    path = target.run_dir / "completions" / "C2.json"
    elsewhere = target.run_dir / "C2.bytes"
    elsewhere.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(elsewhere)
    return target.run_dir, target.output


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (_stopped_run, "run_incomplete"),
        (_no_prices, "prices_missing"),
        (_too_many_attempts, "run_manifest_invalid"),
        (_short_run_id, "run_id_invalid"),
        (_renamed_output, "output_name_mismatch"),
        (_stale_answers, "output_exists"),
        (_stale_score, "output_exists"),
        (_edited_answers, "hash_mismatch"),
        (_edited_receipt, "hash_mismatch"),
        (_foreign_receipt, "prepared_drift"),
        (_torn_attempt_log, "attempt_log_invalid"),
        (_key_in_an_attempt, "secret_found"),
        (_token_in_an_answer, "secret_found"),
        (_linked_prompt_directory, "output_exists"),
        (_linked_answers, "run_layout_invalid"),
        (_missing_answer_file, "run_layout_invalid"),
        (_file_at_the_output, "output_exists"),
    ],
)
def test_publish_refuses_incomplete_existing_or_tampered_runs(
    complete_run: _CompleteRun,
    incomplete_run: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mutate: Callable[[_Publishable], tuple[Path, Path]],
    code: str,
) -> None:
    """Nothing reaches the results directory until every check has passed."""
    # No key is exported, so a credential refusal here is the shape scan
    # rather than a comparison against the environment.
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    run_dir = _run_copy(complete_run.run_dir, tmp_path)
    output = tmp_path / "docs" / "results" / _PUBLISH_RUN_ID
    output.parent.mkdir(parents=True)
    source, target = mutate(_Publishable(run_dir, output, incomplete_run))
    before = _files(target) if target.is_dir() else None
    capsys.readouterr()

    refused = _publish(source, target)

    assert refused == 2
    error = cast(dict[str, Any], json.loads(capsys.readouterr().err))
    assert error["error"]["code"] == code
    assert (_files(target) if target.is_dir() else None) == before
    assert not list(target.parent.glob(".*.partial"))


def test_publish_refuses_a_file_holding_the_exported_credential(
    complete_run: _CompleteRun,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A credential of no recognizable shape is never published either."""
    plain = "9f2c41d7b8e05a63c14f"
    monkeypatch.setenv(API_KEY_ENV, plain)
    run_dir = _run_copy(complete_run.run_dir, tmp_path)
    output = tmp_path / "docs" / "results" / _PUBLISH_RUN_ID
    _plant_in_an_attempt(run_dir, plain)
    capsys.readouterr()

    refused = _publish(run_dir, output)

    assert refused == 2
    error = cast(dict[str, Any], json.loads(capsys.readouterr().err))
    assert error["error"]["code"] == "secret_found"
    assert not output.exists()


def test_publish_help_lists_only_the_fixed_file_set() -> None:
    """The published set is a deliberate constant, not a directory walk."""
    assert _PUBLISHED_FILES == (
        "run_manifest.json",
        "prepare.json",
        *(f"prepared/{label}.json" for label in _LABELS),
        *(f"completions/{label}.json" for label in _LABELS),
        *(f"attempts/{label}.jsonl" for label in _LABELS),
    )
    assert len(set(_PUBLISHED_FILES)) == 14


def _reply_body(content: str) -> bytes:
    """Returns one successful reply carrying the given response text."""
    return json.dumps(
        {
            "id": "gen-gold",
            "model": _MODEL_ID,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        }
    ).encode("utf-8")


class _GoldReplies:
    """Answers each prompt from the gold case its own intent routes to."""

    def __init__(self, cases: Mapping[str, GoldCase]) -> None:
        """Stores the intent-to-case routing this endpoint answers from."""
        self.cases = cases
        self.received: list[_Received] = []

    def __call__(self, _ordinal: int) -> tuple[int, bytes]:
        """Answers the request the fake provider has just recorded."""
        body = cast(dict[str, Any], json.loads(self.received[-1].body))
        messages = cast(list[dict[str, str]], body["messages"])
        payload = cast(
            dict[str, Any],
            json.loads(messages[1]["content"][len(_INPUT_PREFIX) :]),
        )
        case = self.cases[cast(str, payload["intent"])]
        direct = '"direct-filter/1.0"' in messages[0]["content"]
        if isinstance(case, ModelNonReadyCaseV1):
            status = GenerationStatus(case.status)
            question = (
                "Which one?"
                if status is GenerationStatus.NEEDS_CLARIFICATION
                else None
            )
            envelope = (
                DirectFilterResultV1(
                    status=status,
                    clarifying_question=question,
                    missing_slots=case.missing_slots,
                )
                if direct
                else GenerationResultV1(
                    status=status,
                    clarifying_question=question,
                    missing_slots=case.missing_slots,
                )
            )
            return 200, _reply_body(canonical_json(envelope))
        if direct:
            return 200, _reply_body(
                canonical_json(
                    DirectFilterResultV1(
                        status=GenerationStatus.READY,
                        display_filter=case.spec.reference_filter,
                    )
                )
            )
        return 200, _reply_body(
            canonical_json(
                GenerationResultV1(
                    status=GenerationStatus.READY,
                    intent_ir=case.spec.canonical_ir,
                )
            )
        )


def test_published_run_scores_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The committed layout is the one the offline scorer reads.

    No skip: the test image must supply tshark 4.6.8 and the frozen field
    catalog, exactly as tests/test_cli_live.py requires.
    """
    monkeypatch.setenv(API_KEY_ENV, _API_KEY)
    artifacts = generate_model_split(tmp_path / "source")
    by_case: dict[str, GoldCase] = {
        case.case_id: case for case in artifacts.gold.cases
    }
    by_case.update({case.case_id: case for case in artifacts.gold.non_ready})
    routing = {
        item.intent: by_case[artifacts.gold.item_to_case[item.item_id]]
        for item in artifacts.inputs
        if item.split == "dev"
    }
    assert len(routing) == _DEV_ITEMS
    prepare_dir = tmp_path / "model-eval" / _PUBLISH_RUN_ID
    assert (
        model_run.main(
            [
                "prepare",
                "--catalog",
                str(DEFAULT_CATALOG_PATH),
                "--output-dir",
                str(prepare_dir),
                "--source-revision",
                "integration",
            ]
        )
        == 0
    )
    answers = _GoldReplies(routing)
    config = tmp_path / "call.json"
    with _provider(answers) as provider:
        answers.received = provider.received
        _write_config(config, provider.url)
        assert _call(prepare_dir, config, run_id=_PUBLISH_RUN_ID) == 0
        assert len(provider.received) == _PASS_REQUESTS
    published = tmp_path / "docs" / "results" / _PUBLISH_RUN_ID
    assert _publish(prepare_dir / "runs" / _PUBLISH_RUN_ID, published) == 0

    report = score_run(published, code_revision="integration-test")

    ready = sum(isinstance(case, ModelGoldCaseV1) for case in routing.values())
    assert report.items == _PASS_REQUESTS
    assert report.outcomes["strong_exact"] == len(_LABELS) * ready
    assert report.outcomes["abstained"] == _PASS_REQUESTS - len(_LABELS) * ready
    assert sum(report.outcomes.values()) == _PASS_REQUESTS
    scored = published / "scored"
    assert (scored / "summary.json").is_file()
    assert (scored / "summary.md").is_file()
    assert (scored / "outcomes.jsonl").is_file()
    again = score_run(published, code_revision="integration-test", check=True)
    assert again.differences == ()


_README = Path(__file__).parents[1] / "README.md"
_RESULTS = Path(__file__).parents[1] / "docs" / "results"
_README_SECTION = "## Hosted model run"
_README_RUN = re.compile(r"`RUN` below is `([a-z0-9.-]+)`")
_README_REVISION = "0123abc"
_README_PRICES = {"INPUT_PRICE": "0.1", "OUTPUT_PRICE": "0.3"}
# The flags the README prints for each subcommand, as parser destinations;
# ``score`` is the dfilterforge CLI's, the others are the model-run script's.
_README_FLAGS: dict[str, frozenset[str]] = {
    "prepare": frozenset({"catalog", "output_dir", "source_revision"}),
    "call": frozenset(
        {"prepare_dir", "run_id", "config", "max_usd", "source_revision"}
    ),
    "publish": frozenset({"run_dir", "output"}),
    "score": frozenset({"run_dir", "code_revision"}),
}
# Preparation writes through this bind of the test service, so the host
# half of it is where the call step finds the prepared directory.
_README_ARTIFACTS_BIND = "${PWD}/artifacts:/workspace/artifacts"
# What each documented command is typed after. Preparation runs in the test
# image; the call and publish run on the host, because the lab, test and dev
# containers have no network; scoring runs in the lab service, whose Compose
# bind mounts docs/results at /workspace/results.
_README_LAUNCHERS: dict[str, tuple[str, ...]] = {
    "prepare": (
        *("docker", "compose", "--profile", "dev", "run", "--rm"),
        *("--volume", _README_ARTIFACTS_BIND, "test", "python"),
    ),
    "call": ("uv", "run", "--frozen", "python"),
    "publish": ("uv", "run", "--frozen", "python"),
    "score": ("docker", "compose", "--profile", "pilot", "run", "--rm", "lab"),
}
_README_BUILDS = {
    "prepare": "docker compose --profile dev build test",
    "score": "docker compose --profile pilot build lab",
}
_LAB_RESULTS = Path("/workspace/results")
_RESULT_DIR: re.Pattern[str] = getattr(model_run, "_RESULT_DIR")
_SOURCE_MANIFEST: Callable[[], dict[str, str]] = getattr(
    model_run, "_source_manifest"
)


class _Documented(NamedTuple):
    """One command the README prints, as a reader would type it."""

    row: int
    launcher: tuple[str, ...]
    argv: list[str]
    arguments: argparse.Namespace


def _readme_section() -> list[str]:
    """Returns the lines of the README's hosted model run section."""
    lines = _README.read_text(encoding="utf-8").splitlines()
    start = lines.index(_README_SECTION) + 1
    end = next(
        (
            index
            for index in range(start, len(lines))
            if lines[index].startswith("## ")
        ),
        len(lines),
    )
    return lines[start:end]


def _documented_argv(text: str, run_id: str) -> list[str]:
    """Replaces the placeholders exactly as a reader does, then splits."""
    text = re.sub(r"\bRUN\b", run_id, text)
    return shlex.split(text.replace("YOUR_REVISION", _README_REVISION))


def _documented_commands(
    section: Sequence[str], run_id: str
) -> dict[str, _Documented]:
    """Parses every command the section prints, by subcommand.

    Only command lines are read, the ones a reader types from the text
    block. A model-run line is split at the script path and parsed by the
    script's own parser; a ``lab`` line is split after the service name and
    parsed by the ``dfilterforge`` CLI the lab image runs. What comes before
    the split is the launcher.
    """
    commands: dict[str, _Documented] = {}
    for index, line in enumerate(section):
        if not line.startswith(("docker ", "uv ")):
            continue
        if "scripts/model_run.py" in line:
            head, tail = line.split("scripts/model_run.py", 1)
            launcher = tuple(shlex.split(head))
            parser = model_run.build_parser()
        elif " lab " in line:
            head, tail = line.split(" lab ", 1)
            launcher = (*shlex.split(head), "lab")
            parser = cli_module.build_parser()
        else:
            continue
        argv = _documented_argv(tail, run_id)
        assert argv[0] not in commands
        commands[argv[0]] = _Documented(
            index, launcher, argv, parser.parse_args(argv)
        )
    return commands


def _flag_values(argv: Sequence[str]) -> dict[str, str]:
    """Maps every documented ``--flag value`` pair to its destination."""
    assert len(argv) % 2 == 1
    assert all(flag.startswith("--") for flag in argv[1::2])
    return {
        flag[2:].replace("-", "_"): value
        for flag, value in zip(argv[1::2], argv[2::2])
    }


def _documented_config(section: Sequence[str]) -> dict[str, Any]:
    """Returns the call configuration the section shows, prices filled in."""
    (line,) = (line for line in section if line.startswith('{"endpoint_url"'))
    for placeholder, price in _README_PRICES.items():
        line = line.replace(placeholder, price)
    return cast(dict[str, Any], json.loads(line))


def _readme_run_id(section: Sequence[str]) -> str:
    """Returns the committed run directory name the section substitutes."""
    (run_id,) = (
        match.group(1)
        for line in section
        if (match := _README_RUN.search(line)) is not None
    )
    return run_id


def test_readme_commands_match_the_parser() -> None:
    """The run commands the README prints are the ones the CLI defines.

    A renamed or misspelled flag fails here instead of at argparse on the
    first paid run, each command must be typed where it can run, and the
    paths must chain: preparation writes through the artifacts bind into
    the directory the call reads, the call writes the run beside it,
    publish reads the run from there and names the target after it, and
    the lab service scores that target through its own results bind.
    """
    section = _readme_section()
    run_id = _readme_run_id(section)
    assert _RESULT_DIR.fullmatch(run_id)
    assert run_id.startswith("dev-qwen3-32b-")
    if _RESULTS.is_dir():  # The test image carries no docs/ tree.
        assert (_RESULTS / run_id / "prepare.json").is_file()

    commands = _documented_commands(section, run_id)

    assert sorted(commands) == sorted(_README_FLAGS)
    for name, command in commands.items():
        assert command.arguments.command == name
        assert command.launcher == _README_LAUNCHERS[name]
        documented = _flag_values(command.argv)
        assert set(documented) == _README_FLAGS[name]
        for destination, value in documented.items():
            parsed: object = getattr(command.arguments, destination)
            if isinstance(parsed, Path):
                assert parsed == Path(value)
            elif isinstance(parsed, float):
                assert parsed == float(value)
            else:
                assert parsed == value
    for name, build in _README_BUILDS.items():
        assert section.index(build) < commands[name].row
    prepare = commands["prepare"].arguments
    call = commands["call"].arguments
    publish = commands["publish"].arguments
    score = commands["score"].arguments
    host, container = _README_ARTIFACTS_BIND.split(":", 1)
    assert prepare.catalog == DEFAULT_CATALOG_PATH
    assert prepare.source_revision == _README_REVISION
    assert (
        Path(host.removeprefix("${PWD}/"))
        / prepare.output_dir.relative_to(Path(container))
        == call.prepare_dir
    )
    assert call.prepare_dir == Path("artifacts", "model-eval", run_id)
    assert call.run_id == run_id
    assert call.max_usd == 0.25
    assert call.source_revision == _README_REVISION
    assert publish.run_dir == call.prepare_dir / "runs" / run_id
    assert publish.output == Path("docs", "results", run_id)
    assert score.run_dir == _LAB_RESULTS / run_id
    assert score.code_revision == _README_REVISION
    assert (score.check, score.control) == (False, None)


def test_readme_names_only_the_recorded_first_run_model() -> None:
    """The section's prose and commands name qwen/qwen3-32b and no other.

    The run directory, the config and the prose all spell the model size,
    so a stale size in any one of them is caught here rather than by a
    reader who types it.
    """
    section = _readme_section()
    text = "\n".join(section)
    first_step = next(
        index for index, line in enumerate(section) if line.startswith("1. ")
    )
    intro = "\n".join(section[:first_step])
    sizes = set(re.findall(r"qwen3-(\d+)b", text, flags=re.IGNORECASE))

    assert sizes == {"32"}
    assert "qwen/qwen3-32b" in intro
    assert "deepinfra" in intro
    assert _readme_run_id(section) in intro


def test_frozen_prompts_awaiting_a_call_match_the_model_side_code() -> None:
    """A committed prompt set still waiting for its call matches the tree.

    The call refuses with ``prepare_code_mismatch`` as soon as a file that
    decides a prompt differs from the digest its ``prepare.json`` recorded,
    so an edit to one of those files after the freeze would otherwise
    surface only at the paid step. A results directory that already holds
    its published ``run_manifest.json`` was checked by its own call and is
    left alone, so later edits stay free once a run is in.
    """
    if not _RESULTS.is_dir():
        pytest.skip("the test image carries no docs/ tree")
    current = _SOURCE_MANIFEST()
    awaiting = [
        path.parent
        for path in sorted(_RESULTS.glob("*/prepare.json"))
        if not (path.parent / "run_manifest.json").exists()
    ]

    for run_dir in awaiting:
        recorded = dict(_manifest(run_dir).source_files)
        changed = sorted(
            name
            for name in set(recorded) | set(current)
            if recorded.get(name) != current.get(name)
        )
        assert not changed, f"{run_dir.name}: re-freeze after {changed}"


def test_readme_call_config_is_the_recorded_first_run() -> None:
    """The documented call configuration is accepted as the first run's.

    It must parse as the call step's own config model once the reader
    fills in the prices, and it must request qwen/qwen3-32b from deepinfra
    alone, with fallbacks off and the documented reasoning switch.
    """
    section = _readme_section()
    document = _documented_config(section)
    config_model: Any = getattr(model_run, "CallConfigV1")

    config_model.model_validate(document)
    settings = RequestSettingsV1.model_validate(document["settings"])
    prices = TokenPricesV1.model_validate(document["prices"])

    assert set(document) == {"endpoint_url", "settings", "prices"}
    assert document["endpoint_url"].endswith("/chat/completions")
    assert settings.model_id == "qwen/qwen3-32b"
    assert settings.openrouter is not None
    assert settings.openrouter.provider_order == ("deepinfra",)
    assert settings.openrouter.allow_fallbacks is False
    assert settings.openrouter.reasoning == "enabled_false"
    assert (prices.usd_per_million_input, prices.usd_per_million_output) == (
        0.1,
        0.3,
    )
