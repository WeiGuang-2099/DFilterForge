"""Gold-field recall is counted per retrieval depth; test stays aggregate."""

from collections.abc import Sequence
import dataclasses
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import cast, Protocol

import pytest

from dfilterforge import model_split
from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import file_sha256
from dfilterforge.catalog_runtime import DEFAULT_CATALOG_PATH
from dfilterforge.catalog_runtime import freeze_catalog
from dfilterforge.catalog_runtime import open_frozen_catalog
from dfilterforge.errors import DFilterForgeError
from dfilterforge.field_catalog import FieldType
from dfilterforge.field_retrieval import FieldRetrievalItemV1
from dfilterforge.field_retrieval import FieldRetrievalResultV1
from dfilterforge.generation import RetrievedFieldV1
from dfilterforge.intent_ir import MissingSlot
from dfilterforge.model_cases import ModelNonReadyCase
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import model_semantic_cases
from dfilterforge.model_split import ModelInputItemV1
from dfilterforge.model_split import ModelSplitArtifacts
from dfilterforge.runner import TsharkRunner

_ROOT = Path(__file__).parents[1]
_DEV_IDS = tuple(f"mei-{index:04d}" for index in range(1, 17))
_TEST_IDS = tuple(f"mei-{index:04d}" for index in range(1001, 1033))
_SOURCE_FILES = (
    "scripts/retrieval_recall.py",
    "src/dfilterforge/field_retrieval.py",
    "src/dfilterforge/generation.py",
    "src/dfilterforge/intent_ir.py",
    "src/dfilterforge/model_cases.py",
    "src/dfilterforge/model_dev_cases.py",
    "src/dfilterforge/model_split.py",
    "src/dfilterforge/model_test_cases.py",
)
# Gold fields placed at chosen ranks; every other slot holds a filler.
# mei-0002 needs ip.ttl and tcp, and ip.ttl only enters at depth 32.
_PLACEMENTS: dict[str, dict[str, int]] = {
    "mei-0001": {"ip.ttl": 1, "tcp": 2},
    "mei-0002": {"ip.ttl": 20},
    "mei-0011": {"dns": 1, "ip.dst": 5},
}
_EMPTY_ITEM = "mei-0003"
# The figures below were measured on the pilot cases, the first eight dev
# and sixteen test compositions with no non-ready gold, which are the items
# _DEV_IDS and _TEST_IDS name. Pinning the table keeps them independent of
# later cases; CI measures recall over the whole split.
_PILOT_DEV_CASES = 8
_PILOT_TEST_CASES = 16


@pytest.fixture(name="pilot_cases", autouse=True)
def fixture_pilot_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    """Generates every split in this module from the pilot cases alone."""
    dev = model_split.ready_dev_cases()[:_PILOT_DEV_CASES]
    test = model_split.ready_test_cases()[:_PILOT_TEST_CASES]
    monkeypatch.setattr(model_split, "ready_dev_cases", lambda: dev)
    monkeypatch.setattr(model_split, "ready_test_cases", lambda: test)
    monkeypatch.setattr(model_split, "model_non_ready_cases", lambda: ())


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


class _Recall(Protocol):
    """Typed view of the standalone retrieval-recall script."""

    retrieve_fields: _Retrieve

    def measure(
        self,
        catalog: Path,
        splits: Sequence[str],
        top_ks: Sequence[int] = ...,
        *,
        source_revision: str = ...,
        detail_splits: Sequence[str] = ...,
    ) -> dict[str, object]:
        ...

    def main(self, argv: Sequence[str] | None = None) -> int:
        ...


def _load_retrieval_recall() -> _Recall:
    path = _ROOT / "scripts" / "retrieval_recall.py"
    spec = importlib.util.spec_from_file_location("retrieval_recall", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("retrieval recall script cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    # The dataclass decorator resolves string annotations through here.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast(_Recall, module)


retrieval_recall = _load_retrieval_recall()


class _MetadataRunner(TsharkRunner):
    """Serves the small reports tests/test_catalog_runtime.py freezes."""

    def version(self) -> str:
        return "4.6.8"

    def report(self, name: str) -> bytes:
        if name == "fields":
            return (
                b"P\tTCP\ttcp\n"
                b"F\tPort\ttcp.port\tFT_UINT16\ttcp\tBASE_DEC\n"
                b"F\tBytes\ttcp.payload\tFT_BYTES\ttcp\t\n"
            )
        if name == "values":
            return b"V\ttcp.port\t443\tHTTPS\n"
        return b"default"


@pytest.fixture(name="catalog", scope="module")
def fixture_catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Freezes a fixture inventory so no tshark binary is needed."""
    path = tmp_path_factory.mktemp("catalog") / "fixture.sqlite3"
    freeze_catalog(path, _MetadataRunner())
    return path


def _field(rank: int, name: str) -> RetrievedFieldV1:
    return RetrievedFieldV1(
        rank=rank,
        abbreviation=name,
        field_type=FieldType.INTEGER,
        protocol=name.partition(".")[0],
        display_name=f"Field {rank}",
    )


def _placed_retrieve(
    path: Path, items: Sequence[FieldRetrievalItemV1], *, top_k: int = 16
) -> tuple[FieldRetrievalResultV1, ...]:
    """Honours ``top_k`` exactly and puts gold fields where told."""
    assert path.is_file()
    results: list[FieldRetrievalResultV1] = []
    for item in items:
        placed = {
            rank: name
            for name, rank in _PLACEMENTS.get(item.item_id, {}).items()
        }
        fields = tuple(
            _field(rank, placed.get(rank, f"filler.f{rank}"))
            for rank in range(1, top_k + 1)
        )
        if item.item_id == _EMPTY_ITEM:
            fields = ()
        results.append(
            FieldRetrievalResultV1(item_id=item.item_id, fields=fields)
        )
    return tuple(results)


@pytest.fixture(name="placed")
def fixture_placed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replaces the catalog scan with the placement fake."""
    monkeypatch.setattr(retrieval_recall, "retrieve_fields", _placed_retrieve)


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _at(receipt: dict[str, object], split: str, k: int) -> dict[str, object]:
    block = _mapping(_mapping(receipt["splits"])[split])
    return _mapping(_mapping(block["per_k"])[str(k)])


def _widest_context_bytes(catalog: Path, top_k: int) -> int:
    queries = tuple(
        FieldRetrievalItemV1(item_id=item_id, intent="fixture")
        for item_id in _DEV_IDS
    )
    return max(
        len(canonical_json(result.fields).encode("utf-8"))
        for result in _placed_retrieve(catalog, queries, top_k=top_k)
    )


@pytest.mark.usefixtures("placed")
def test_recall_counts_every_gold_field_by_rank(catalog: Path) -> None:
    receipt = retrieval_recall.measure(catalog, ("dev",), (32, 16))

    assert set(_mapping(receipt["splits"])) == {"dev"}
    assert receipt["top_ks"] == [16, 32]
    # Found at depth 16: mei-0001 both, mei-0011 dns and ip.dst.
    assert _at(receipt, "dev", 16) == {
        "items": 16,
        "all_in": 1,
        "macro_recall": 0.104,  # (1 + 2/3) / 16 = 0.10416...
        "micro_found": 4,
        "micro_total": 36,
        "nonprotocol_found": 2,
        "nonprotocol_total": 28,
        "max_context_bytes": _widest_context_bytes(catalog, 16),
        "empty_contexts": 1,
    }
    # Depth 32 is its own pass, and only there does mei-0002's ip.ttl show.
    at_32 = _at(receipt, "dev", 32)
    assert (at_32["all_in"], at_32["micro_found"]) == (1, 5)
    assert at_32["nonprotocol_found"] == 3
    assert at_32["macro_recall"] == 0.135  # (1 + 1/2 + 2/3) / 16
    per_item = _mapping(
        _mapping(_mapping(receipt["splits"])["dev"])["per_item"]
    )
    assert tuple(sorted(per_item)) == _DEV_IDS
    gold = {
        item_id: _mapping(per_item[item_id])["gold"]
        for item_id in ("mei-0001", "mei-0002", "mei-0003", "mei-0011")
    }
    assert gold == {
        "mei-0001": {"ip.ttl": 1, "tcp": 2},
        "mei-0002": {"ip.ttl": 20, "tcp": None},
        "mei-0003": {"ip.ttl": None, "udp": None},
        "mei-0011": {"dns": 1, "ip.dst": 5, "udp": None},
    }
    first = _mapping(per_item["mei-0001"])
    assert first["case_id"] == "tcp-expiring-ttl"
    assert _mapping(per_item[_EMPTY_ITEM])["context_bytes"] == 2
    assert json.loads(canonical_json(receipt)) == receipt


def _shallow_only_retrieve(
    path: Path, items: Sequence[FieldRetrievalItemV1], *, top_k: int = 16
) -> tuple[FieldRetrievalResultV1, ...]:
    """A ranker whose depth-8 context is not a prefix of its deeper ones.

    mei-0001 sees its ip.ttl gold field at rank 1 at depth 8 and nowhere in
    the depth-16 or depth-32 context, so recall derived by truncating one
    deep pass differs from recall measured on each depth's own pass.
    """
    assert path.is_file()
    results: list[FieldRetrievalResultV1] = []
    for item in items:
        fields = [
            _field(rank, f"filler.f{rank}") for rank in range(1, top_k + 1)
        ]
        if item.item_id == "mei-0001" and top_k == 8:
            fields[0] = _field(1, "ip.ttl")
        results.append(
            FieldRetrievalResultV1(item_id=item.item_id, fields=tuple(fields))
        )
    return tuple(results)


def test_every_depth_is_measured_on_its_own_pass(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requested: list[int] = []

    def recorded(
        path: Path, items: Sequence[FieldRetrievalItemV1], *, top_k: int = 16
    ) -> tuple[FieldRetrievalResultV1, ...]:
        requested.append(top_k)
        return _shallow_only_retrieve(path, items, top_k=top_k)

    monkeypatch.setattr(retrieval_recall, "retrieve_fields", recorded)
    receipt = retrieval_recall.measure(catalog, ("dev",), (32, 8, 16))

    found = {k: _at(receipt, "dev", k)["micro_found"] for k in (8, 16, 32)}
    assert found == {8: 1, 16: 0, 32: 0}
    assert _at(receipt, "dev", 8)["macro_recall"] == 0.031  # (1/2) / 16
    # One timed and one traced pass per depth, and no deeper pass reused.
    assert sorted(requested) == [8, 8, 16, 16, 32, 32]
    # Per-item ranks come from the deepest pass, where ip.ttl is absent.
    per_item = _mapping(
        _mapping(_mapping(receipt["splits"])["dev"])["per_item"]
    )
    assert _mapping(per_item["mei-0001"])["gold"] == {
        "ip.ttl": None,
        "tcp": None,
    }


@pytest.mark.usefixtures("placed")
def test_test_split_is_reported_without_per_item_detail(
    catalog: Path,
) -> None:
    receipt = retrieval_recall.measure(catalog, ("dev", "test"), (16,))

    splits = _mapping(receipt["splits"])
    assert "per_item" in _mapping(splits["dev"])
    test_block = _mapping(splits["test"])
    assert set(test_block) == {"items", "per_k"}
    assert test_block["items"] == 32
    assert _at(receipt, "test", 16)["micro_total"] == 68
    assert receipt["detail_splits"] == ["dev"]
    test_case_ids = {
        case.case_id for case in model_semantic_cases() if case.split == "test"
    }
    assert len(test_case_ids) == 16
    encoded = canonical_json(receipt)
    for identifier in (*test_case_ids, *_TEST_IDS):
        assert identifier not in encoded
    with pytest.raises(DFilterForgeError) as caught:
        retrieval_recall.measure(
            catalog, ("dev", "test"), (16,), detail_splits=("dev", "train")
        )
    assert caught.value.code == "detail_split_invalid"


@pytest.mark.usefixtures("placed")
def test_receipt_records_source_files_catalog_identity_and_timing(
    catalog: Path,
) -> None:
    receipt = retrieval_recall.measure(
        catalog, ("dev", "test"), (8, 16), source_revision="rev-7"
    )

    assert receipt["schema_version"] == "retrieval-recall/1.0"
    assert receipt["source_revision"] == "rev-7"
    sources = _mapping(receipt["source_files"])
    assert sorted(sources) == sorted(_SOURCE_FILES)
    for name, digest in sources.items():
        assert isinstance(digest, str)
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        assert digest == file_sha256(_ROOT / name)
    with open_frozen_catalog(catalog) as frozen:
        expected = {
            "file_name": frozen.file_name,
            "file_sha256": frozen.file_sha256,
            "sqlite_sha256": frozen.sqlite_sha256,
            "catalog_hash": frozen.catalog_hash,
            "tshark_version": frozen.tshark_version,
        }
    assert receipt["catalog"] == expected
    timing = _mapping(receipt["timing"])
    assert set(timing) == {"dev", "test"}
    for split in ("dev", "test"):
        entries = _mapping(timing[split])
        assert set(entries) == {"8", "16"}
        for entry in entries.values():
            measured = _mapping(entry)
            seconds = measured["seconds"]
            peak = measured["tracemalloc_peak_bytes"]
            assert isinstance(seconds, float) and seconds >= 0
            assert isinstance(peak, int) and not isinstance(peak, bool)
            assert peak > 0
    assert isinstance(receipt["timing_note"], str)


def _unexpected_retrieve(
    path: Path, items: Sequence[FieldRetrievalItemV1], *, top_k: int = 16
) -> tuple[FieldRetrievalResultV1, ...]:
    """Fails the test when a refused run still scans the catalog."""
    del path, top_k
    raise AssertionError(f"unexpected retrieval of {len(items)} items")


@pytest.mark.usefixtures("placed")
def test_main_writes_once_and_refuses_to_overwrite(
    catalog: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "receipts" / "before.json"
    argv = [
        "--catalog",
        str(catalog),
        "--output",
        str(output),
        "--source-revision",
        "test-rev",
    ]

    assert retrieval_recall.main(argv) == 0
    written = output.read_bytes()
    text = written.decode("utf-8")
    receipt = _mapping(json.loads(text))
    assert text == canonical_json(receipt) + "\n"
    assert receipt["top_ks"] == [8, 16, 32]
    splits = _mapping(receipt["splits"])
    assert set(splits) == {"dev"}
    printed = _mapping(json.loads(capsys.readouterr().out))
    assert printed == {"dev": _mapping(splits["dev"])["per_k"]}

    # An existing receipt is refused before any catalog pass starts.
    monkeypatch.setattr(
        retrieval_recall, "retrieve_fields", _unexpected_retrieve
    )
    assert retrieval_recall.main(argv) == 2
    error = _mapping(json.loads(capsys.readouterr().err))["error"]
    assert _mapping(error)["code"] == "output_exists"
    assert output.read_bytes() == written

    with pytest.raises(SystemExit) as exited:
        retrieval_recall.main([*argv[:-1], "has space"])
    assert exited.value.code == 2

    monkeypatch.setattr(retrieval_recall, "retrieve_fields", _placed_retrieve)
    wide = tmp_path / "wide.json"
    wide_argv = [*argv[:3], str(wide), *argv[4:], "--include-test"]
    assert retrieval_recall.main(wide_argv) == 0
    wide_splits = _mapping(
        json.loads(wide.read_text(encoding="utf-8"))["splits"]
    )
    assert "per_item" in _mapping(wide_splits["dev"])
    assert "per_item" not in _mapping(wide_splits["test"])


def test_a_receipt_that_appears_mid_measurement_is_kept(
    catalog: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "before.json"
    rival = b"written by another run\n"

    def racing(
        path: Path, items: Sequence[FieldRetrievalItemV1], *, top_k: int = 16
    ) -> tuple[FieldRetrievalResultV1, ...]:
        if not output.exists():
            output.write_bytes(rival)
        return _placed_retrieve(path, items, top_k=top_k)

    monkeypatch.setattr(retrieval_recall, "retrieve_fields", racing)
    status = retrieval_recall.main(
        [
            "--catalog",
            str(catalog),
            "--output",
            str(output),
            "--source-revision",
            "test-rev",
        ]
    )

    assert status == 2
    error = _mapping(_mapping(json.loads(capsys.readouterr().err))["error"])
    assert error["code"] == "output_exists"
    assert output.read_bytes() == rival


def _invalid_retrieve(
    path: Path, items: Sequence[FieldRetrievalItemV1], *, top_k: int = 16
) -> tuple[FieldRetrievalResultV1, ...]:
    """Returns one field more than the requested depth allows."""
    return tuple(
        FieldRetrievalResultV1(
            item_id=result.item_id,
            fields=(*result.fields, _field(top_k + 1, "extra.field")),
        )
        for result in _placed_retrieve(path, items, top_k=top_k)
    )


def _schema_retrieve(
    path: Path, items: Sequence[FieldRetrievalItemV1], *, top_k: int = 16
) -> tuple[FieldRetrievalResultV1, ...]:
    """Fails the way a malformed catalog projection fails."""
    del path, items, top_k
    return (FieldRetrievalResultV1.model_validate({"item_id": "mei-0001"}),)


@pytest.mark.parametrize(
    ("retrieve", "output_name", "code"),
    [
        (_invalid_retrieve, "out.json", "retrieval_invalid"),
        (_schema_retrieve, "out.json", "schema_invalid"),
        (_placed_retrieve, "blocker/out.json", "io_error"),
    ],
)
def test_main_reports_failures_as_one_error_envelope(
    catalog: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    retrieve: _Retrieve,
    output_name: str,
    code: str,
) -> None:
    monkeypatch.setattr(retrieval_recall, "retrieve_fields", retrieve)
    (tmp_path / "blocker").write_bytes(b"a file where a directory must go")
    output = tmp_path / output_name

    status = retrieval_recall.main(
        [
            "--catalog",
            str(catalog),
            "--output",
            str(output),
            "--source-revision",
            "test-rev",
        ]
    )

    assert status == 2
    error = _mapping(_mapping(json.loads(capsys.readouterr().err))["error"])
    assert error["code"] == code
    assert not output.exists()


def test_missing_catalog_is_reported_without_a_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "out.json"
    argv = ["--catalog", str(tmp_path / "absent.sqlite3"), "--output"]

    assert (
        retrieval_recall.main([*argv, str(output), "--source-revision", "r"])
        == 2
    )
    error = _mapping(_mapping(json.loads(capsys.readouterr().err))["error"])
    assert error["code"] == "catalog_unavailable"
    assert not output.exists()


@pytest.mark.parametrize(
    ("splits", "top_ks", "code"),
    [
        (("train",), (16,), "split_invalid"),
        ((), (16,), "split_invalid"),
        (("test", "dev"), (16,), "split_invalid"),
        (("dev",), (33,), "top_k_invalid"),
        (("dev",), (0,), "top_k_invalid"),
        (("dev",), (), "top_k_invalid"),
    ],
)
def test_measure_rejects_unknown_splits_and_top_ks(
    catalog: Path, splits: tuple[str, ...], top_ks: tuple[int, ...], code: str
) -> None:
    with pytest.raises(DFilterForgeError) as caught:
        retrieval_recall.measure(catalog, splits, top_ks)
    assert caught.value.code == code


def test_an_item_without_gold_stops_the_measurement(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unrouted(output_dir: Path) -> ModelSplitArtifacts:
        artifacts = generate_model_split(output_dir)
        stray = ModelInputItemV1(
            item_id="mei-9999",
            intent="Show TCP packets.",
            user_assumptions=("fixture",),
            split="dev",
        )
        return dataclasses.replace(artifacts, inputs=(*artifacts.inputs, stray))

    monkeypatch.setattr(retrieval_recall, "generate_model_split", unrouted)
    with pytest.raises(DFilterForgeError) as caught:
        retrieval_recall.measure(catalog, ("dev",), (16,))
    assert caught.value.code == "gold_routing_invalid"


def test_non_ready_items_have_no_recall_to_measure(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        model_split,
        "model_non_ready_cases",
        lambda: (
            ModelNonReadyCase(
                case_id="unnamed-server",
                split="dev",
                status="needs_clarification",
                paraphrases=("Show traffic to the file server.", "Find it."),
                missing_slots=(MissingSlot.ADDRESS,),
                rationale="No host is given.",
            ),
        ),
    )

    receipt = retrieval_recall.measure(catalog, ("dev",), (16,))

    assert _at(receipt, "dev", 16)["items"] == 16


def test_every_dev_intent_retrieves_over_the_real_catalog() -> None:
    # No skip: the test image must supply the frozen field catalog.
    receipt = retrieval_recall.measure(DEFAULT_CATALOG_PATH, ("dev",), (16,))

    dev = _mapping(_mapping(receipt["splits"])["dev"])
    assert dev["items"] == 16
    at_16 = _at(receipt, "dev", 16)
    # Pins the protocol and name-coverage ranking; the ranker it replaced
    # reached all_in 1 and micro_found 4 here.
    assert at_16["all_in"] == 10
    assert at_16["micro_found"] == 27
    assert at_16["micro_total"] == 36
    assert at_16["nonprotocol_total"] == 28
    assert at_16["empty_contexts"] == 0
    max_context_bytes = at_16["max_context_bytes"]
    assert isinstance(max_context_bytes, int)
    assert max_context_bytes <= 32 * 1024
