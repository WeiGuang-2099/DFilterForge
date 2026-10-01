"""The web capture evidence: frame tables, anchors and exit status.

Frame tables are regenerated from the split and feedback generators and
checked against the benchmark recipes and the witness names directly. The
anchor files of a temporary repository are written from the regenerated
document, then edited to fail one check at a time. The test of the committed
file skips where the test image carries no docs/ tree.
"""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import pytest

from dfilterforge.benchmark import BenchmarkProbe
from dfilterforge.benchmark import generate_benchmark
from dfilterforge.model_split import generate_model_split
from dfilterforge.witnesses import WITNESS_NAMES

_ROOT = Path(__file__).resolve().parents[1]
# The curated captures in document order: dev then test, scored probes in
# gold order, then the split's unscored feedback probe.
_ORDER = (
    ("semantic-11", "dev", "scored"),
    ("semantic-17", "dev", "scored"),
    ("semantic-23", "dev", "scored"),
    ("semantic-29", "dev", "feedback"),
    ("semantic-31", "test", "scored"),
    ("semantic-37", "test", "scored"),
    ("semantic-43", "test", "scored"),
    ("semantic-35", "test", "feedback"),
)
_GATE = Path("docs/decisions/evidence/test-freeze-gate.json")
_FREEZE = Path("src/dfilterforge/held_out_freeze.json")
_SPEC = Path("docs/results/dev-fixture-2026-01-01/scored/specs/case-a.json")
_CAPTURES = Path("docs/decisions/evidence/web/captures.json")
Document = dict[str, Any]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "export_web_evidence", _ROOT / "scripts" / "export_web_evidence.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("export_web_evidence cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


evidence = _load()


@pytest.fixture(name="document", scope="module")
def fixture_document() -> Document:
    return evidence.build_captures()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _edit_json(path: Path, edit: Callable[[Any], None]) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    edit(value)
    _write_json(path, value)


def _manifest_row(row: Document) -> Document:
    return {
        key: row[key]
        for key in ("probe_id", "split", "capture_sha256", "size_bytes")
    }


@pytest.fixture(name="repo")
def fixture_repo(tmp_path: Path, document: Document) -> Path:
    """A repository whose anchors all agree with the regenerated document."""
    rows: list[Document] = document["probes"]
    _write_json(
        tmp_path / _GATE,
        {
            "measurement_identity": {
                "capture_manifest": [
                    _manifest_row(row)
                    for row in rows
                    if row["role"] == "scored"
                ],
                "feedback_manifest": [
                    _manifest_row(row)
                    for row in rows
                    if row["role"] == "feedback"
                ],
            }
        },
    )
    _write_json(
        tmp_path / _FREEZE,
        {
            "digests": {
                "gold": "0" * 64,
                **{
                    row["probe_id"]: row["capture_sha256"]
                    for row in rows
                    if row["split"] == "test"
                },
            }
        },
    )
    _write_json(
        tmp_path / _SPEC,
        {
            "split": "dev",
            "status": "ready",
            "probes": [
                {
                    "probe_id": row["probe_id"],
                    "capture_sha256": row["capture_sha256"],
                    "expected_frames": [1],
                }
                for row in rows
                if (row["split"], row["role"]) == ("dev", "scored")
            ],
        },
    )
    # A non-ready specification has no probes, and a probe outside the
    # curated captures is no anchor; neither is checked.
    _write_json(
        tmp_path / _SPEC.parent / "not-ready.json",
        {"split": "dev", "status": "needs_clarification"},
    )
    _write_json(
        tmp_path / _SPEC.parent / "suite-probe.json",
        {
            "split": "dev",
            "status": "ready",
            "probes": [{"probe_id": "semantic-01", "capture_sha256": "0" * 64}],
        },
    )
    (tmp_path / _CAPTURES).parent.mkdir(parents=True)
    (tmp_path / _CAPTURES).write_bytes(evidence.render(document))
    return tmp_path


def test_rows_cover_the_curated_captures_in_split_and_role_order(
    document: Document,
) -> None:
    assert document["schema_version"] == "capture-frames/1.0"
    assert [
        (row["probe_id"], row["split"], row["role"])
        for row in document["probes"]
    ] == list(_ORDER)


def test_frames_name_each_benchmark_recipe_then_each_witness(
    document: Document, tmp_path: Path
) -> None:
    benchmark = {
        probe.probe_id: probe.recipes
        for probe in generate_benchmark(tmp_path / "benchmark")
    }
    for row in document["probes"]:
        recipes = benchmark[row["probe_id"]]
        frames = row["frames"]

        assert row["benchmark_frames"] == len(recipes)
        assert [frame["n"] for frame in frames] == list(
            range(1, len(recipes) + len(WITNESS_NAMES) + 1)
        )
        assert [frame["name"] for frame in frames] == [
            *recipes,
            *WITNESS_NAMES,
        ]
        assert [frame["kind"] for frame in frames] == (
            ["recipe"] * len(recipes) + ["witness"] * len(WITNESS_NAMES)
        )


def test_capture_identities_match_the_gold_and_the_freeze(
    document: Document, tmp_path: Path
) -> None:
    split = generate_model_split(tmp_path / "split")
    gold = {
        expected.probe_id: expected.capture_sha256
        for case in split.gold.cases
        for expected in case.spec.probes
    }
    freeze = json.loads((_ROOT / _FREEZE).read_text(encoding="utf-8"))
    digests = freeze["digests"]
    rows = {row["probe_id"]: row for row in document["probes"]}

    for probe in split.probes:
        assert rows[probe.probe_id]["size_bytes"] == (
            probe.capture_path.stat().st_size
        )
    for probe_id, row in rows.items():
        if row["role"] == "scored":
            assert row["capture_sha256"] == gold[probe_id]
        if row["split"] == "test":
            assert row["capture_sha256"] == digests[probe_id]


def test_render_is_sorted_indented_and_ends_in_one_lf(
    document: Document,
) -> None:
    data = evidence.render(document)

    assert data == evidence.render(evidence.build_captures())
    assert data.endswith(b"}\n") and not data.endswith(b"\n\n")
    assert b"\r" not in data
    assert data.decode("utf-8") == (
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )


def test_write_then_both_checks_pass(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed = (repo / _CAPTURES).read_bytes()
    (repo / _CAPTURES).unlink()

    assert evidence.main(["--repo", str(repo), "captures", "--write"]) == 0
    written = (repo / _CAPTURES).read_bytes()
    assert written == committed
    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "path": _CAPTURES.as_posix(),
        "probes": len(_ORDER),
        "frames": sum(
            len(row["frames"]) for row in json.loads(written)["probes"]
        ),
        "size_bytes": len(written),
        "sha256": hashlib.sha256(written).hexdigest(),
    }
    assert evidence.main(["--repo", str(repo), "captures", "--check"]) == 0
    assert evidence.main(["--repo", str(repo), "check"]) == 0


def _rename_first_frame(repo: Path) -> None:
    value = json.loads((repo / _CAPTURES).read_text(encoding="utf-8"))
    value["probes"][0]["frames"][0]["name"] = "edited"
    (repo / _CAPTURES).write_bytes(evidence.render(value))


def _drop_captures(repo: Path) -> None:
    (repo / _CAPTURES).unlink()


def _resize_in_gate(repo: Path) -> None:
    def edit(value: Any) -> None:
        value["measurement_identity"]["feedback_manifest"][0]["size_bytes"] += 1

    _edit_json(repo / _GATE, edit)


def _drop_from_gate(repo: Path) -> None:
    def edit(value: Any) -> None:
        del value["measurement_identity"]["capture_manifest"][4]

    _edit_json(repo / _GATE, edit)


def _reseal_in_freeze(repo: Path) -> None:
    def edit(value: Any) -> None:
        value["digests"]["semantic-35"] = "0" * 64

    _edit_json(repo / _FREEZE, edit)


def _reseal_in_spec(repo: Path) -> None:
    def edit(value: Any) -> None:
        value["probes"][1]["capture_sha256"] = "0" * 64

    _edit_json(repo / _SPEC, edit)


def _resplit_spec(repo: Path) -> None:
    def edit(value: Any) -> None:
        value["split"] = "test"
        del value["probes"][1:]

    _edit_json(repo / _SPEC, edit)


def _drop_spec(repo: Path) -> None:
    (repo / _SPEC).unlink()


@pytest.mark.parametrize(
    ("change", "failures"),
    [
        (
            _rename_first_frame,
            [f"{_CAPTURES.as_posix()} differs from a regeneration"],
        ),
        (_drop_captures, [f"{_CAPTURES.as_posix()} is missing"]),
        (
            _resize_in_gate,
            [f"semantic-29: size_bytes differs from {_GATE.as_posix()}"],
        ),
        (
            _drop_from_gate,
            [f"semantic-37: {_GATE.as_posix()} lists it 0 times"],
        ),
        (
            _reseal_in_freeze,
            [f"semantic-35: capture_sha256 differs from {_FREEZE.as_posix()}"],
        ),
        (
            _reseal_in_spec,
            [f"semantic-17: capture_sha256 differs from {_SPEC.as_posix()}"],
        ),
        (
            _resplit_spec,
            [
                f"semantic-11: split differs from {_SPEC.as_posix()}",
                "semantic-17: no committed scored specification names it",
                "semantic-23: no committed scored specification names it",
            ],
        ),
        (
            _drop_spec,
            [
                f"{probe_id}: no committed scored specification names it"
                for probe_id in ("semantic-11", "semantic-17", "semantic-23")
            ],
        ),
    ],
)
def test_each_check_fails_alone(
    repo: Path,
    document: Document,
    change: Callable[[Path], None],
    failures: list[str],
) -> None:
    assert not evidence.check(repo, document)

    change(repo)

    assert evidence.check(repo, document) == failures


def test_a_failing_check_exits_one_and_write_refuses_on_an_anchor(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _reseal_in_freeze(repo)
    (repo / _CAPTURES).unlink()

    assert evidence.main(["--repo", str(repo), "captures", "--write"]) == 1
    assert not (repo / _CAPTURES).exists()
    assert evidence.main(["--repo", str(repo), "check"]) == 1
    errors = [
        json.loads(line)["error"]
        for line in capsys.readouterr().err.splitlines()
    ]
    assert {error["code"] for error in errors} == {"check_failed"}
    assert len(errors) == 3


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"[]", "schema_invalid"),
        (
            b'{"measurement_identity": {"capture_manifest": {}}}',
            "schema_invalid",
        ),
        (b'{"measurement_identity": NaN}', "schema_invalid"),
        (b"\xff\xfe", "schema_invalid"),
        (b"{", "schema_invalid"),
    ],
)
def test_an_unreadable_anchor_exits_two(
    repo: Path,
    capsys: pytest.CaptureFixture[str],
    content: bytes,
    code: str,
) -> None:
    (repo / _GATE).write_bytes(content)

    assert evidence.main(["--repo", str(repo), "check"]) == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == code


def test_a_missing_anchor_exits_two(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / _FREEZE).unlink()

    assert evidence.main(["--repo", str(repo), "check"]) == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "io_error"


def test_an_input_over_the_ceiling_exits_two(
    repo: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(evidence, "MAX_INPUT_BYTES", 16)

    assert evidence.main(["--repo", str(repo), "check"]) == 2
    error = json.loads(capsys.readouterr().err)["error"]
    assert error["code"] == "input_too_large"


def _capture(*lengths: int) -> bytes:
    header = (0xA1B2C3D4).to_bytes(4, "little") + bytes(20)
    records = b"".join(
        bytes(8) + length.to_bytes(4, "little") * 2 + bytes(length)
        for length in lengths
    )
    return header + records


def test_record_count_counts_records_and_refuses_a_torn_capture() -> None:
    assert evidence.record_count(_capture()) == 0
    assert evidence.record_count(_capture(60, 54, 1)) == 3
    for torn in (
        _capture(60)[:-1],
        _capture(60) + bytes(15),
        b"\xa1\xb2\xc3\xd4" + bytes(20),
        bytes(10),
    ):
        with pytest.raises(evidence.EvidenceError) as caught:
            evidence.record_count(torn)
        assert caught.value.code == "capture_invalid"


def test_a_probe_without_its_tail_or_frames_is_refused(tmp_path: Path) -> None:
    capture = tmp_path / "semantic-99.pcap"
    capture.write_bytes(_capture(60, 60))
    recipes = ("syn", *WITNESS_NAMES)

    with pytest.raises(evidence.EvidenceError) as caught:
        evidence.probe_row(
            BenchmarkProbe("semantic-99", capture, recipes[:-1]),
            "dev",
            "scored",
        )
    assert caught.value.code == "witness_tail_missing"
    with pytest.raises(evidence.EvidenceError) as caught:
        evidence.probe_row(
            BenchmarkProbe("semantic-99", capture, recipes), "dev", "scored"
        )
    assert caught.value.code == "frame_count_mismatch"


@pytest.mark.skipif(
    not (_ROOT / "docs" / "results").is_dir(),
    reason="The test image carries no docs/ tree",
)
def test_the_committed_frame_tables_match_a_regeneration_and_every_anchor(
    document: Document,
) -> None:
    assert evidence.check(_ROOT, document) == []
