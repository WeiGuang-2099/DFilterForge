"""The web capture evidence: frame tables, packet lists, anchors, exits.

Frame tables are regenerated from the split and feedback generators and
checked against the benchmark recipes and the witness names directly; the
packet lists come from the pinned tshark. The anchor files of a temporary
repository are written from the regenerated documents, then edited to fail
one check at a time; its Reel pool is one run whose receipts the pinned
tshark gives. The test of the committed files, the Reel pick's predicate
trace and the verifier v1 replay included, skips where the test image
carries no docs/ tree.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from datetime import timezone
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
from dfilterforge.evaluation import aggregate_metrics
from dfilterforge.evaluation import evaluate_probe
from dfilterforge.evaluation import EvaluationReceiptV1
from dfilterforge.model_split import generate_model_split
from dfilterforge.packet_list import PacketListRunner
from dfilterforge.score_summary import ConditionLabel
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import OutcomeV1
from dfilterforge.shortcuts import ShortcutHitV1
from dfilterforge.shortcuts import ShortcutRule
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
_PACKETS = Path("docs/decisions/evidence/web/packets.json")
_EXHIBITS = Path("docs/decisions/evidence/web/exhibits.json")
_REGISTRY = Path("docs/decisions/evidence/test-runs.json")
_ADEQUACY = Path("docs/ablations/evidence/005-probe-adequacy-simplified.json")
_RUN = "test-fixture-2026-01-01"
_SCORED = Path("docs/results") / _RUN / "scored"
_TEST_PROBES = ("semantic-31", "semantic-37", "semantic-43")
# The fixture pool's executed answers, with a shortcut token or None and
# their v1 and v2 verdicts: a witness-only miss, the reference, a miss a
# benchmark frame shows, a shortcut, the reference again from a typed
# condition, and a case only the witness tail can score.
_ANSWERS: tuple[
    tuple[ConditionLabel, str, str, str, str | None, str, str], ...
] = (
    (
        "C1",
        "mei-1031",
        "tcp-destination-not-https",
        "tcp && !(tcp.port == 443)",
        None,
        "strong_exact",
        "silent_wrong",
    ),
    (
        "C1",
        "mei-1032",
        "tcp-destination-not-https",
        "tcp.dstport != 443",
        None,
        "strong_exact",
        "strong_exact",
    ),
    (
        "C2",
        "mei-1031",
        "tcp-destination-not-https",
        "tcp.dstport == 53",
        None,
        "silent_wrong",
        "silent_wrong",
    ),
    (
        "C2",
        "mei-1032",
        "tcp-destination-not-https",
        "tcp.dstport != 443 && frame.number >= 1",
        "frame.number",
        "shortcut",
        "shortcut",
    ),
    (
        "C3",
        "mei-1031",
        "tcp-destination-not-https",
        "tcp.dstport != 443",
        None,
        "strong_exact",
        "strong_exact",
    ),
    (
        "C1",
        "mei-1067",
        "ttl-between",
        "ip.ttl > 1 && ip.ttl < 64",
        None,
        "unscorable",
        "strong_exact",
    ),
)
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


@pytest.fixture(name="packets", scope="module")
def fixture_packets() -> Document:
    return evidence.build_packets(PacketListRunner())


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


def _freeze(document: Document) -> Document:
    """A freeze record holding the regenerated test captures' digests."""
    return {
        "digests": {
            "gold": "0" * 64,
            **{
                row["probe_id"]: row["capture_sha256"]
                for row in document["probes"]
                if row["split"] == "test"
            },
        }
    }


def _row(
    condition: ConditionLabel,
    item_id: str,
    case_id: str,
    outcome: OutcomeV1,
    **fields: Any,
) -> bytes:
    """One outcome row as the scorer writes it, with one trailing LF."""
    return (
        ItemOutcomeV1(
            condition=condition,
            item_id=item_id,
            case_id=case_id,
            outcome=outcome,
            gold_field_count=1,
            latency_ms=0.0,
            **fields,
        ).model_dump_json()
        + "\n"
    ).encode("utf-8")


@pytest.fixture(name="exhibit_inputs", scope="module")
def fixture_exhibit_inputs(
    document: Document, tmp_path_factory: pytest.TempPathFactory
) -> dict[Path, bytes]:
    """A one-run Reel pool, its v1 anchor and the exhibits it replays to.

    Each receipt holds the frames the pinned tshark gives on the scored
    captures. Pass B and an unused row stay out of the pool, and neither a
    non-executed answer nor non-ready gold enters the replay.
    """
    root = tmp_path_factory.mktemp("exhibits")
    split = generate_model_split(root / "split")
    benchmark = {
        probe.probe_id: probe.capture_path.read_bytes()
        for probe in generate_benchmark(root / "benchmark")
    }
    captures = {probe.probe_id: probe.capture_path for probe in split.probes}
    specs = {case.case_id: case.spec for case in split.gold.cases}
    runner = PacketListRunner()
    files: dict[Path, bytes] = {
        _REGISTRY: json.dumps(
            {
                "runs": [
                    {
                        "role": "aa_pass_a",
                        "run_id": _RUN,
                        "status": "published",
                    },
                    {
                        "role": "aa_pass_b",
                        "run_id": "test-fixture-passb-2026-01-01",
                        "status": "published",
                    },
                    {
                        "role": "winner_small",
                        "run_id": "test-fixture-small-2026-01-01",
                        "status": "unused",
                    },
                ]
            }
        ).encode("utf-8"),
        _ADEQUACY: json.dumps(
            {
                "measurement_identity": {
                    "capture_manifest": [
                        {
                            "probe_id": probe_id,
                            "capture_sha256": hashlib.sha256(
                                benchmark[probe_id]
                            ).hexdigest(),
                        }
                        for probe_id in _TEST_PROBES
                    ]
                }
            }
        ).encode("utf-8"),
    }
    rows: list[bytes] = []
    for condition, item_id, case_id, answer, token, _, _ in _ANSWERS:
        spec = specs[case_id]
        files[_SCORED / "specs" / f"{case_id}.json"] = (
            spec.model_dump_json().encode("utf-8")
        )
        probes = tuple(
            evaluate_probe(
                expected.probe_id,
                expected.expected_frames,
                runner.run(captures[expected.probe_id], answer).frames,
                0.0,
            )
            for expected in spec.probes
        )
        files[_SCORED / "receipts" / condition / f"{item_id}.json"] = (
            EvaluationReceiptV1(
                run_id=_RUN,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                code_revision="fixture",
                environment_hash="0" * 64,
                data_hash="0" * 64,
                candidate_filter=answer,
                reference_filter=spec.reference_filter,
                probes=probes,
                metrics=aggregate_metrics(probes),
            )
            .model_dump_json()
            .encode("utf-8")
        )
        exact = tuple(probe.exact for probe in probes)
        hits = (
            ()
            if token is None
            else (
                ShortcutHitV1(rule=ShortcutRule.CAPTURE_POSITION, token=token),
            )
        )
        outcome = OutcomeV1.SILENT_WRONG
        if all(exact):
            outcome = OutcomeV1.SHORTCUT if hits else OutcomeV1.STRONG_EXACT
        rows.append(
            _row(
                condition,
                item_id,
                case_id,
                outcome,
                candidate_filter=answer if condition in ("C1", "C2") else None,
                probe_exact=exact,
                shortcuts=hits,
            )
        )
    rows.append(
        _row("C4", "mei-1031", "tcp-destination-not-https", OutcomeV1.INVALID)
    )
    rows.append(
        _row(
            "C1",
            "mei-1501",
            "unnamed-server",
            OutcomeV1.FALSE_READY,
            gold_status="needs_clarification",
        )
    )
    files[_SCORED / "outcomes.jsonl"] = b"".join(rows)
    for path, data in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(data)
    _write_json(root / _FREEZE, _freeze(document))
    files[_EXHIBITS] = evidence.render(
        evidence.build_exhibits_document(root, runner)
    )
    return files


@pytest.fixture(name="repo")
def fixture_repo(
    tmp_path: Path,
    document: Document,
    packets: Document,
    exhibit_inputs: dict[Path, bytes],
) -> Path:
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
    _write_json(tmp_path / _FREEZE, _freeze(document))
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
    (tmp_path / _PACKETS).write_bytes(evidence.render(packets))
    for path, data in exhibit_inputs.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(data)
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


def test_packet_lists_follow_the_frame_tables_capture_by_capture(
    document: Document, packets: Document
) -> None:
    assert packets["schema_version"] == "capture-packets/1.0"
    assert packets["tshark_version"] == "4.6.8"
    for frames, listed in zip(
        document["probes"], packets["probes"], strict=True
    ):
        assert listed["probe_id"] == frames["probe_id"]
        assert listed["capture_sha256"] == frames["capture_sha256"]
        assert [row["n"] for row in listed["frames"]] == [
            row["n"] for row in frames["frames"]
        ]
        assert {row["direction"] for row in listed["frames"]} <= {
            "out",
            "in",
            "other",
        }


def test_a_stale_or_missing_packet_list_fails_and_write_restores_it(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed = (repo / _PACKETS).read_bytes()
    (repo / _PACKETS).write_bytes(committed.replace(b"TCP", b"UDP", 1))

    assert evidence.main(["--repo", str(repo), "packets", "--check"]) == 1
    assert evidence.main(["--repo", str(repo), "check"]) == 1
    (repo / _PACKETS).unlink()
    assert evidence.main(["--repo", str(repo), "check"]) == 1
    errors = [
        json.loads(line)["error"]["message"]
        for line in capsys.readouterr().err.splitlines()
    ]
    assert errors == [
        f"{_PACKETS.as_posix()} differs from a regeneration",
        f"{_PACKETS.as_posix()} differs from a regeneration",
        f"{_PACKETS.as_posix()} is missing",
    ]
    assert evidence.main(["--repo", str(repo), "packets", "--write"]) == 0
    assert (repo / _PACKETS).read_bytes() == committed
    assert evidence.main(["--repo", str(repo), "check"]) == 0


def test_a_trace_is_named_only_by_a_run_a_typed_condition_and_an_item(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert evidence.trace_path(
        "test-qwen3-32b-2026-09-26", "C4", "mei-1038"
    ) == Path(
        "docs/decisions/evidence/web/traces/test-qwen3-32b-2026-09-26/C4/"
        "mei-1038.json"
    )
    for run_id, condition, item_id in (
        ("../docs", "C4", "mei-1038"),
        ("test-qwen3-32b-2026-09-26", "C1", "mei-1038"),
        ("test-qwen3-32b-2026-09-26", "C4", "../x"),
    ):
        arguments = ["trace", "--run", run_id, "--condition", condition]
        assert evidence.main([*arguments, "--item", item_id]) == 2
        error = json.loads(capsys.readouterr().err)["error"]
        assert error["code"] == "answer_unknown"


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


def test_the_pool_replays_each_executed_ready_answer_once(
    exhibit_inputs: dict[Path, bytes],
) -> None:
    document = json.loads(exhibit_inputs[_EXHIBITS])
    source = document["sources"]["hosted_test"]
    benchmark_frames = {
        row["probe_id"]: row["v1_frames"] for row in source["probes"]
    }

    assert document["schema_version"] == "verifier-exhibits/1.0"
    assert "witness tail" in document["notes"][0]
    assert source["runs"] == [_RUN]
    assert [
        (row["probe_id"], row["v1_frames"], row["v2_frames"])
        for row in source["probes"]
    ] == [
        ("semantic-31", 26, 59),
        ("semantic-37", 27, 60),
        ("semantic-43", 33, 66),
    ]
    assert source["unscorable_cases"] == ["ttl-between"]
    answers = source["answers"]
    assert [
        (row["condition"], row["item_id"], row["case_id"], row["v1"], row["v2"])
        for row in answers
    ] == [(c, i, k, v1, v2) for c, i, k, _, _, v1, v2 in _ANSWERS]
    receipt = _SCORED / "receipts" / "C1" / "mei-1031.json"
    assert answers[0]["receipt"] == receipt.as_posix()
    assert answers[0]["receipt_sha256"] == (
        hashlib.sha256(exhibit_inputs[receipt]).hexdigest()
    )
    assert [row for row in answers if "witness_frames" in row] == answers[:1]
    frames = answers[0]["witness_frames"]
    assert {frame["witness"] for frame in frames} == {
        "server-ack",
        "server-ack-next",
        "keepalive-server-ack",
        "server-syn",
        "server-fin-ack",
    }
    for frame in frames:
        assert frame["n"] > benchmark_frames[frame["probe_id"]]
        assert (frame["answer_matched"], frame["should_match"]) == (False, True)


def test_exhibits_write_restores_and_check_refuses_an_edit(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed = (repo / _EXHIBITS).read_bytes()
    (repo / _EXHIBITS).unlink()

    assert evidence.main(["--repo", str(repo), "exhibits", "--check"]) == 1
    assert evidence.main(["--repo", str(repo), "exhibits", "--write"]) == 0
    assert (repo / _EXHIBITS).read_bytes() == committed
    assert evidence.main(["--repo", str(repo), "exhibits", "--check"]) == 0
    (repo / _EXHIBITS).write_bytes(
        committed.replace(b'"v1": "strong_exact"', b'"v1": "silent_wrong"', 1)
    )
    assert evidence.main(["--repo", str(repo), "exhibits", "--check"]) == 1
    assert evidence.main(["--repo", str(repo), "check"]) == 1
    out, err = capsys.readouterr()
    assert [json.loads(line) for line in out.splitlines()] == 2 * [
        {
            "path": _EXHIBITS.as_posix(),
            "sha256": hashlib.sha256(committed).hexdigest(),
            "size_bytes": len(committed),
        }
    ]
    assert [
        json.loads(line)["error"]["message"] for line in err.splitlines()
    ] == [
        f"{_EXHIBITS.as_posix()} is missing",
        f"{_EXHIBITS.as_posix()} differs from a replay",
        f"{_EXHIBITS.as_posix()} differs from a replay",
    ]


def _reseal_v1_anchor(repo: Path) -> None:
    def edit(value: Any) -> None:
        manifest = value["measurement_identity"]["capture_manifest"]
        manifest[1]["capture_sha256"] = "0" * 64

    _edit_json(repo / _ADEQUACY, edit)


def _relabel_spec(repo: Path) -> None:
    def edit(value: Any) -> None:
        probe = value["probes"][0]
        probe["expected_frames"] = probe["expected_frames"][1:]

    _edit_json(
        repo / _SCORED / "specs" / "tcp-destination-not-https.json", edit
    )


def _retouch_receipt(repo: Path) -> None:
    path = repo / _SCORED / "receipts" / "C1" / "mei-1032.json"
    receipt = EvaluationReceiptV1.model_validate_json(path.read_bytes())
    first = receipt.probes[0]
    probes = (
        evaluate_probe(
            first.probe_id,
            first.expected_frames,
            first.candidate_frames[1:],
            0.0,
        ),
        *receipt.probes[1:],
    )
    update = {"probes": probes, "metrics": aggregate_metrics(probes)}
    path.write_text(
        receipt.model_copy(update=update).model_dump_json(), encoding="utf-8"
    )


def _break_registry(repo: Path) -> None:
    (repo / _REGISTRY).write_text("[]", encoding="utf-8")


def _break_outcomes(repo: Path) -> None:
    path = repo / _SCORED / "outcomes.jsonl"
    path.write_bytes(path.read_bytes() + b"{}\n")


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (_reseal_v1_anchor, "anchor_mismatch"),
        (_relabel_spec, "gold_invalid"),
        (_retouch_receipt, "replay_mismatch"),
        (_break_registry, "input_invalid"),
        (_break_outcomes, "input_invalid"),
    ],
)
def test_an_exhibit_input_failing_its_check_exits_two(
    repo: Path,
    capsys: pytest.CaptureFixture[str],
    change: Callable[[Path], None],
    code: str,
) -> None:
    change(repo)

    assert evidence.main(["--repo", str(repo), "exhibits", "--check"]) == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == code


@pytest.mark.skipif(
    not (_ROOT / "docs" / "results").is_dir(),
    reason="The test image carries no docs/ tree",
)
def test_the_committed_exhibits_are_a_replay_of_the_reel_pool() -> None:
    assert evidence.exhibits_failures(_ROOT, PacketListRunner()) == []
    document = json.loads((_ROOT / _EXHIBITS).read_text(encoding="utf-8"))
    answers = document["sources"]["hosted_test"]["answers"]
    accepted = [row for row in answers if row["v1"] == "strong_exact"]
    killed = [row for row in accepted if row["v2"] == "silent_wrong"]
    assert (len(answers), len(accepted), len(killed)) == (971, 731, 11)
    # The one shortcut on v1 that only a witness frame shows to be wrong.
    (pick,) = (
        row
        for row in answers
        if row["v1"] == "shortcut" and row["v2"] == "silent_wrong"
    )
    assert (pick["run_id"], pick["condition"], pick["item_id"]) == (
        "test-qwen3.5-9b-2026-09-26",
        "C3",
        "mei-1066",
    )
    assert [
        (frame["probe_id"], frame["n"], frame["witness"])
        for frame in pick["witness_frames"]
    ] == [
        ("semantic-31", 58, "dns-query-to-private-low"),
        ("semantic-37", 59, "dns-query-to-private-low"),
        ("semantic-43", 65, "dns-query-to-private-low"),
    ]


@pytest.mark.skipif(
    not (_ROOT / "docs" / "results").is_dir(),
    reason="The test image carries no docs/ tree",
)
def test_the_committed_frame_tables_match_a_regeneration_and_every_anchor(
    document: Document,
) -> None:
    assert evidence.check(_ROOT, document) == []
    # packets.json and every committed trace, the Reel pick's among them,
    # rebuild to the same bytes.
    assert evidence.tshark_failures(_ROOT, PacketListRunner()) == []
    trace = json.loads(
        (
            _ROOT
            / evidence.trace_path("test-qwen3-32b-2026-09-26", "C4", "mei-1038")
        ).read_text(encoding="utf-8")
    )
    probe = trace["result"]["trace"]["probes"][1]
    assert probe["probe_id"] == "semantic-37"
    assert probe["counterexample_frames"] == [60]
    assert [
        (leaf["display_filter"], leaf["matched_frames"])
        for leaf in probe["candidate_predicates"]
    ] == [("tcp.srcport == 443", [60]), ("tcp.completeness.fin == true", [])]
