"""The probe adequacy gate: waivers, receipt shape and exit status.

A recorded runner stands in for tshark: it answers each reference filter
and compiled canonical IR with its case's labels on all six probes, each
authored mutation with its mutation labels on all six probes, a chosen set
of filters with the labels of their case, and everything else with no
frames.
"""

from collections.abc import Sequence
import dataclasses
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import cast, Protocol

import pytest

from dfilterforge.canonical import content_sha256
from dfilterforge.compiler import compile_intent
from dfilterforge.errors import DFilterForgeError
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import model_semantic_cases
from dfilterforge.model_split import ModelGoldCaseV1
from dfilterforge.model_split import ModelSplitArtifacts
from dfilterforge.model_split import MUTANT_WAIVERS
from dfilterforge.mutants import Mutant
from dfilterforge.mutants import MutantCategory
from dfilterforge.mutants import MutantWaiver
from dfilterforge.mutants import single_site_mutants
from dfilterforge.runner import RunnerError
from dfilterforge.runner import RunResult
from dfilterforge.runner import TsharkRunner

_ROOT = Path(__file__).parents[1]
# The committed ready cases, their single-site mutants and the dev share,
# as the gate receipt of the case expansion records them.
_CASES = 52
_MUTANTS = 344
_DEV_MUTANTS = 72
# The receipt hashes the runner binary with POSIX-only open flags.
_POSIX_ONLY = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="measure() records a Linux runner environment",
)
_Answers = dict[tuple[str, str], tuple[int, ...]]


class _Survivor(Protocol):
    """Typed view of the gate's survivor record."""

    case_id: str
    split: str
    category: str
    edit: str
    display_filter: str


class _Gate(Protocol):
    """Typed view of the standalone probe adequacy script."""

    def Survivor(
        self,
        case_id: str,
        split: str,
        category: str,
        edit: str,
        display_filter: str,
    ) -> _Survivor:
        ...

    def apply_waivers(
        self,
        survivors: Sequence[_Survivor],
        waivers: Sequence[MutantWaiver],
    ) -> tuple[list[dict[str, object]], list[MutantWaiver]]:
        ...

    def measure(
        self,
        runner: TsharkRunner,
        *,
        source_revision: str,
        strict: bool,
        waivers: Sequence[MutantWaiver] = ...,
    ) -> dict[str, object]:
        ...

    def main(self, argv: Sequence[str] | None = None) -> int:
        ...


def _load_gate() -> _Gate:
    path = _ROOT / "scripts" / "probe_adequacy.py"
    spec = importlib.util.spec_from_file_location("probe_adequacy", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("probe adequacy script cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    # The dataclass decorator resolves string annotations through here.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast(_Gate, module)


probe_adequacy = _load_gate()


class _AnswerRunner(TsharkRunner):
    """Answers filters from a table keyed by probe id and filter text."""

    def __init__(
        self,
        answers: _Answers,
        *,
        rejected: frozenset[str] = frozenset(),
        failing: frozenset[str] = frozenset(),
        corrupt: bool = False,
    ) -> None:
        super().__init__(tshark="/usr/bin/true")
        self.answers = answers
        self.rejected = rejected
        self.failing = failing
        self.corrupt = corrupt

    def version(self) -> str:
        return "4.6.8"

    def run(self, capture: Path, display_filter: str) -> RunResult:
        if display_filter in self.rejected:
            raise RunnerError(
                "filter_rejected", "tshark rejected the display filter"
            )
        if display_filter in self.failing:
            raise RunnerError("timeout", "tshark exceeded the time limit")
        digest = hashlib.sha256(capture.read_bytes()).hexdigest()
        return RunResult(
            self.answers.get((capture.stem, display_filter), ()),
            1.0,
            "0" * 64 if self.corrupt else digest,
        )


@pytest.fixture(name="split", scope="module")
def fixture_split(
    tmp_path_factory: pytest.TempPathFactory,
) -> ModelSplitArtifacts:
    """One generated split; the gate regenerates identical bytes."""
    return generate_model_split(tmp_path_factory.mktemp("split"))


@pytest.fixture(name="gold", scope="module")
def fixture_gold(split: ModelSplitArtifacts) -> dict[str, ModelGoldCaseV1]:
    return {case.case_id: case for case in split.gold.cases}


def _gold_answers(split: ModelSplitArtifacts) -> _Answers:
    """Answers every case's three authored filters with their labels."""
    answers: _Answers = {}
    for case in model_semantic_cases():
        for probe in split.probes:
            labels = case.labels(probe)
            answers[(probe.probe_id, case.reference_filter)] = labels
            answers[(probe.probe_id, compile_intent(case.canonical_ir))] = (
                labels
            )
            answers[(probe.probe_id, case.mutation_filter)] = case.labels(
                probe, mutation=True
            )
    return answers


def _canonical_runs(gold: dict[str, ModelGoldCaseV1]) -> int:
    """Canonical label runs: six per case whose text is not its reference."""
    return 6 * sum(
        compile_intent(case.spec.canonical_ir) != case.spec.reference_filter
        for case in gold.values()
    )


def _exact(case: ModelGoldCaseV1, display_filter: str) -> _Answers:
    """Makes one filter match the case's labels on every probe."""
    return {
        (probe.probe_id, display_filter): probe.expected_frames
        for probe in case.spec.probes
    }


def _mutant_filters(
    case: ModelGoldCaseV1, category: MutantCategory
) -> list[tuple[str, str]]:
    return [
        (mutant.edit, compile_intent(mutant.intent))
        for mutant in single_site_mutants(case.spec.canonical_ir)
        if mutant.category is category
    ]


def _waived(gold: dict[str, ModelGoldCaseV1]) -> _Answers:
    """Makes every declared waiver's mutant survive, as tshark does."""
    answers: _Answers = {}
    for waiver in MUTANT_WAIVERS:
        answers.update(_exact(gold[waiver.case_id], waiver.display_filter))
    return answers


def _planted(
    split: ModelSplitArtifacts, gold: dict[str, ModelGoldCaseV1]
) -> _Answers:
    """Gold exact, plus the field swaps of one dev and one test case."""
    answers = _gold_answers(split)
    for case_id in ("ack-to-https", "tcp-destination-not-https"):
        case = gold[case_id]
        for _, text in _mutant_filters(case, MutantCategory.FIELD_SWAP):
            answers.update(_exact(case, text))
    return answers


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _rows(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    return [_mapping(row) for row in cast(list[object], value)]


def _survivor(case_id: str, edit: str) -> _Survivor:
    return probe_adequacy.Survivor(
        case_id, "dev", "field-swap", edit, f"filter for {edit}"
    )


def _waiver(
    case_id: str, edit: str, display_filter: str | None = None
) -> MutantWaiver:
    return MutantWaiver(
        case_id=case_id,
        edit=edit,
        display_filter=display_filter or f"filter for {edit}",
        kind="equivalent",
        reason="Both filters select the same packets.",
    )


def test_waivers_mark_their_survivors_and_keep_gate_order() -> None:
    survivors = [_survivor("a", "0: x"), _survivor("b", "1: y")]

    rows, stale = probe_adequacy.apply_waivers(
        survivors, [_waiver("b", "1: y")]
    )

    assert stale == []
    assert [
        (row["case_id"], row["waived"], row["waiver_kind"]) for row in rows
    ] == [
        ("a", False, None),
        ("b", True, "equivalent"),
    ]
    assert rows[1] == {
        "case_id": "b",
        "split": "dev",
        "category": "field-swap",
        "edit": "1: y",
        "filter": "filter for 1: y",
        "waived": True,
        "waiver_kind": "equivalent",
    }


def test_a_waiver_needs_both_case_and_edit_or_it_is_stale() -> None:
    other_case = _waiver("b", "0: x")
    other_edit = _waiver("a", "1: y")
    matching = _waiver("a", "0: x")

    rows, stale = probe_adequacy.apply_waivers(
        [_survivor("a", "0: x")], [other_case, matching, other_edit]
    )

    assert [row["waived"] for row in rows] == [True]
    assert stale == [other_case, other_edit]
    assert probe_adequacy.apply_waivers([], [matching]) == ([], [matching])


def test_a_waiver_whose_label_moved_to_another_filter_is_stale() -> None:
    # A reordered gold gives "0: x" to a different mutant: the survivor
    # keeps the label but not the filter the reason was written for.
    moved = _waiver("a", "0: x", "the filter that was reasoned about")

    rows, stale = probe_adequacy.apply_waivers(
        [_survivor("a", "0: x")], [moved]
    )

    assert [(row["waived"], row["waiver_kind"]) for row in rows] == [
        (False, None)
    ]
    assert stale == [moved]


def test_two_waivers_for_one_mutant_are_refused() -> None:
    with pytest.raises(DFilterForgeError) as caught:
        probe_adequacy.apply_waivers(
            [], [_waiver("a", "0: x"), _waiver("a", "0: x", "another filter")]
        )

    assert caught.value.code == "waiver_duplicate"


@_POSIX_ONLY
def test_receipt_counts_survivors_by_split_and_category(
    split: ModelSplitArtifacts,
    gold: dict[str, ModelGoldCaseV1],
) -> None:
    last = single_site_mutants(gold["tcp-expiring-ttl"].spec.canonical_ir)[-1]
    rejected = compile_intent(last.intent)
    ack_swaps = _mutant_filters(gold["ack-to-https"], MutantCategory.FIELD_SWAP)
    waived_edit, waived_filter = ack_swaps[0]
    stale = _waiver("ack-to-https", "9: not an edit")
    runner = _AnswerRunner(
        _planted(split, gold), rejected=frozenset({rejected})
    )

    receipt = probe_adequacy.measure(
        runner,
        source_revision="unit-test",
        strict=True,
        waivers=[
            _waiver("ack-to-https", waived_edit, waived_filter),
            stale,
        ],
    )

    assert receipt["schema_version"] == "probe-adequacy/1.1"
    assert receipt["mode"] == "strict"
    assert receipt["source_revision"] == "unit-test"
    assert receipt["case_count"] == _CASES
    assert receipt["categories"] == [c.value for c in MutantCategory]
    assert receipt["label_checks"] == {
        "reference_checked": _CASES * 6,
        "canonical_checked": _CASES * 6,
        "mutation_checked": _CASES * 6,
    }
    assert receipt["rejected"] == [
        {
            "case_id": "tcp-expiring-ttl",
            "split": "dev",
            "category": "boundary",
            "edit": last.edit,
            "filter": rejected,
            "error_code": "filter_rejected",
        }
    ]
    assert receipt["mutants"] == {
        "generated": _MUTANTS,
        "duplicates": 0,
        "executed": _MUTANTS,
        "killed": _MUTANTS - 5,
        "survived": 4,
        "rejected": 1,
        "uncompilable": 0,
        "waived": 1,
        "unwaived": 3,
    }
    counts = _mapping(receipt["counts"])
    dev, test = _mapping(counts["dev"]), _mapping(counts["test"])
    assert (dev["executed"], dev["survived"], dev["waived"]) == (
        _DEV_MUTANTS,
        2,
        1,
    )
    assert (test["executed"], test["survived"], test["waived"]) == (
        _MUTANTS - _DEV_MUTANTS,
        2,
        0,
    )
    dev_swaps = _mapping(_mapping(dev["by_category"])["field-swap"])
    assert dev_swaps["survived"] == 2
    boundary = _mapping(_mapping(dev["by_category"])["boundary"])
    assert boundary["rejected"] == 1
    for scope in (dev, test):
        categories = [
            _mapping(value) for value in _mapping(scope["by_category"]).values()
        ]
        assert (
            sum(cast(int, c["killed"]) for c in categories) == scope["killed"]
        )
    survivors = _rows(receipt["survivors"])
    assert [(row["case_id"], row["split"]) for row in survivors] == [
        ("ack-to-https", "dev"),
        ("ack-to-https", "dev"),
        ("tcp-destination-not-https", "test"),
        ("tcp-destination-not-https", "test"),
    ]
    assert survivors[0] == {
        "case_id": "ack-to-https",
        "split": "dev",
        "category": "field-swap",
        "edit": waived_edit,
        "filter": ack_swaps[0][1],
        "waived": True,
        "waiver_kind": "equivalent",
    }
    assert survivors[2]["filter"] == "tcp.port != 443"
    assert receipt["waivers"] == {
        "declared": 2,
        "applied": 1,
        "stale": [
            {
                "case_id": "ack-to-https",
                "edit": "9: not an edit",
                "filter": "filter for 9: not an edit",
                "kind": "equivalent",
            }
        ],
    }
    assert receipt["failures"] == {
        "label_mismatches": 0,
        "canonical_mismatches": 0,
        "mutation_label_mismatches": 0,
        "undistinguished_mutations": 0,
        "unwaived_survivors": 3,
        "stale_waivers": 1,
    }
    assert receipt["passed"] is False
    cases = _rows(receipt["cases"])
    assert [row["case_id"] for row in cases] == list(gold)
    assert all(row["label_mismatches"] == [] for row in cases)
    assert all(row["canonical_mismatches"] == [] for row in cases)
    assert all(row["mutation_label_mismatches"] == [] for row in cases)
    assert sum(cast(int, row["mutants_executed"]) for row in cases) == (
        _MUTANTS
    )
    assert [row["case_id"] for row in cases if row["mutants_rejected"]] == [
        "tcp-expiring-ttl"
    ]
    runtime = _mapping(receipt["runtime"])
    # Six reference runs per case, the canonical runs whose text differs,
    # six mutation runs per case and three runs per mutant; the rejected
    # mutant stops at its first probe with no runtime.
    assert runtime["timed_runs"] == (
        _CASES * 6 + _canonical_runs(gold) + _CASES * 6 + (_MUTANTS - 1) * 3
    )
    assert runtime["p50_ms"] == runtime["p95_ms"] == 1.0
    identity = _mapping(receipt["measurement_identity"])
    assert receipt["measurement_identity_sha256"] == content_sha256(identity)
    manifest = _rows(identity["capture_manifest"])
    assert [(row["probe_id"], row["split"]) for row in manifest] == [
        ("semantic-11", "dev"),
        ("semantic-17", "dev"),
        ("semantic-23", "dev"),
        ("semantic-31", "test"),
        ("semantic-37", "test"),
        ("semantic-43", "test"),
    ]
    sources = _mapping(identity["source_files"])
    assert "scripts/probe_adequacy.py" in sources
    assert "src/dfilterforge/mutants.py" in sources
    environment = _mapping(identity["environment"])
    assert environment["tshark_version"] == "4.6.8"
    assert environment["catalog_hash"] is None
    json.dumps(receipt, allow_nan=False)


@_POSIX_ONLY
def test_label_mismatches_on_either_split_are_recorded(
    split: ModelSplitArtifacts,
    gold: dict[str, ModelGoldCaseV1],
) -> None:
    oracles = {case.case_id: case for case in model_semantic_cases()}
    probes = {probe.probe_id: probe for probe in split.probes}
    answers = _gold_answers(split)
    # A dev reference is wrong on a test probe and a test canonical IR on
    # a dev probe: neither probe is one its case is scored on.
    dev_case = gold["udp-expiring-ttl"]
    answers[("semantic-31", dev_case.spec.reference_filter)] = (999,)
    test_case = gold["https-without-syn"]
    answers[("semantic-11", compile_intent(test_case.spec.canonical_ir))] = (
        999,
    )
    # A dev mutation is wrong on a test probe, which only its own mutation
    # labels can catch.
    answers[("semantic-43", gold["tcp-expiring-ttl"].mutation_filter)] = (999,)
    blind = gold["aaaa-or-udp-source-dns"]
    answers.update(_exact(blind, blind.mutation_filter))
    answers.update(_waived(gold))
    # The blind mutation also misses its mutation labels wherever those
    # differ from the case's labels.
    blind_misses = sum(
        oracles[blind.case_id].labels(probes[probe.probe_id], mutation=True)
        != probe.expected_frames
        for probe in blind.spec.probes
    )

    receipt = probe_adequacy.measure(
        _AnswerRunner(answers), source_revision="unit-test", strict=False
    )

    assert receipt["mode"] == "report"
    assert blind_misses > 0
    assert receipt["failures"] == {
        "label_mismatches": 1,
        "canonical_mismatches": 1,
        "mutation_label_mismatches": 1 + blind_misses,
        "undistinguished_mutations": 1,
        "unwaived_survivors": 0,
        "stale_waivers": 0,
    }
    cases = {str(row["case_id"]): row for row in _rows(receipt["cases"])}
    assert cases["udp-expiring-ttl"]["label_mismatches"] == [
        {
            "probe_id": "semantic-31",
            "expected": oracles["udp-expiring-ttl"].labels(
                probes["semantic-31"]
            ),
            "frames": (999,),
        }
    ]
    assert cases["udp-expiring-ttl"]["canonical_mismatches"] == []
    assert cases["https-without-syn"]["canonical_mismatches"] == [
        {
            "probe_id": "semantic-11",
            "expected": oracles["https-without-syn"].labels(
                probes["semantic-11"]
            ),
            "frames": (999,),
        }
    ]
    assert cases["https-without-syn"]["label_mismatches"] == []
    assert cases["tcp-expiring-ttl"]["mutation_label_mismatches"] == [
        {
            "probe_id": "semantic-43",
            "expected": oracles["tcp-expiring-ttl"].labels(
                probes["semantic-43"], mutation=True
            ),
            "frames": (999,),
        }
    ]
    assert cases["tcp-expiring-ttl"]["mutation_killing_probes"] == [
        "semantic-11",
        "semantic-17",
        "semantic-23",
    ]
    assert cases["aaaa-or-udp-source-dns"]["mutation_killing_probes"] == []
    assert cases["dns-a-queries"]["mutation_killing_probes"] == [
        "semantic-11",
        "semantic-17",
        "semantic-23",
    ]
    assert receipt["passed"] is False


@_POSIX_ONLY
def test_duplicate_and_uncompilable_mutants_are_counted_not_run(
    split: ModelSplitArtifacts,
    gold: dict[str, ModelGoldCaseV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uncompilable = Mutant(
        MutantCategory.VALUE_DOMAIN,
        "root: control character",
        IntentIrV1(
            expression=Predicate(
                field="dns.qry.name", operator=Operator.EQ, value="a\x01"
            )
        ),
    )

    def padded(intent: IntentIrV1) -> tuple[Mutant, ...]:
        found = single_site_mutants(intent)
        return (*found, found[0], uncompilable)

    monkeypatch.setattr(probe_adequacy, "single_site_mutants", padded)

    receipt = probe_adequacy.measure(
        _AnswerRunner({**_gold_answers(split), **_waived(gold)}),
        source_revision="unit-test",
        strict=True,
    )

    mutants = _mapping(receipt["mutants"])
    assert (mutants["generated"], mutants["duplicates"]) == (
        _MUTANTS + 2 * _CASES,
        _CASES,
    )
    assert (mutants["executed"], mutants["uncompilable"]) == (
        _MUTANTS,
        _CASES,
    )
    # Only the declared waivers survive, so strict mode passes.
    assert (mutants["survived"], mutants["waived"]) == (4, 4)
    assert receipt["passed"] is True


def _main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: TsharkRunner,
    *flags: str,
) -> tuple[int, Path]:
    output = tmp_path / "receipts" / "adequacy.json"
    monkeypatch.setattr(probe_adequacy, "TsharkRunner", lambda: runner)
    status = probe_adequacy.main(
        ["--output", str(output), "--source-revision", "c3d4060", *flags]
    )
    return status, output


def _error_code(capsys: pytest.CaptureFixture[str]) -> object:
    envelope = _mapping(json.loads(capsys.readouterr().err))
    return _mapping(envelope["error"])["code"]


@_POSIX_ONLY
def test_strict_mode_fails_on_survivors_after_writing_the_receipt(
    split: ModelSplitArtifacts,
    gold: dict[str, ModelGoldCaseV1],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status, output = _main(
        tmp_path, monkeypatch, _AnswerRunner(_planted(split, gold))
    )

    assert status == 1
    raw = output.read_bytes()
    assert b"\r" not in raw
    text = raw.decode("utf-8")
    receipt = _mapping(json.loads(text))
    # Sorted and indented like the other ablation evidence.
    assert text == json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    assert receipt["source_revision"] == "c3d4060"
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 5
    assert _mapping(json.loads(lines[0]))["case_id"] == "ack-to-https"
    summary = _mapping(json.loads(lines[-1]))
    assert summary["passed"] is False
    assert summary["dev"] == {
        "executed": _DEV_MUTANTS,
        "survived": 2,
        "unwaived": 2,
    }


@_POSIX_ONLY
def test_report_mode_records_failures_and_exits_zero(
    split: ModelSplitArtifacts,
    gold: dict[str, ModelGoldCaseV1],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status, output = _main(
        tmp_path, monkeypatch, _AnswerRunner(_planted(split, gold)), "--report"
    )

    receipt = _mapping(json.loads(output.read_text(encoding="utf-8")))
    assert (status, receipt["mode"], receipt["passed"]) == (0, "report", False)


@_POSIX_ONLY
def test_strict_mode_passes_when_only_waived_mutants_survive(
    split: ModelSplitArtifacts,
    gold: dict[str, ModelGoldCaseV1],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = {**_gold_answers(split), **_waived(gold)}

    status, output = _main(tmp_path, monkeypatch, _AnswerRunner(answers))

    receipt = _mapping(json.loads(output.read_text(encoding="utf-8")))
    assert (status, receipt["passed"]) == (0, True)
    waivers = _mapping(receipt["waivers"])
    assert (waivers["declared"], waivers["applied"]) == (4, 4)


@_POSIX_ONLY
def test_strict_mode_fails_when_a_declared_waiver_has_no_survivor(
    split: ModelSplitArtifacts,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Every mutant killed leaves all four declared waivers stale.
    status, output = _main(
        tmp_path, monkeypatch, _AnswerRunner(_gold_answers(split))
    )

    receipt = _mapping(json.loads(output.read_text(encoding="utf-8")))
    assert (status, receipt["passed"]) == (1, False)
    assert _mapping(receipt["failures"])["stale_waivers"] == 4


def test_an_existing_receipt_is_never_replaced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "receipts" / "adequacy.json"
    output.parent.mkdir()
    output.write_text("kept\n", encoding="utf-8")

    status, _ = _main(tmp_path, monkeypatch, _AnswerRunner({}))

    assert status == 2
    assert _error_code(capsys) == "output_exists"
    assert output.read_text(encoding="utf-8") == "kept\n"


@pytest.mark.parametrize(
    ("failure", "code"),
    [("timeout", "timeout"), ("corrupt", "capture_hash_mismatch")],
)
def test_execution_failures_exit_two_in_report_mode(
    split: ModelSplitArtifacts,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
    code: str,
) -> None:
    answers = _gold_answers(split)
    runner = (
        _AnswerRunner(answers, failing=frozenset({"(tcp && ip.ttl == 1)"}))
        if failure == "timeout"
        else _AnswerRunner(answers, corrupt=True)
    )

    status, output = _main(tmp_path, monkeypatch, runner, "--report")

    assert status == 2
    assert _error_code(capsys) == code
    assert not output.exists()


def test_a_probe_without_a_capture_stops_the_gate(
    split: ModelSplitArtifacts,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def without_first_capture(output_dir: Path) -> ModelSplitArtifacts:
        artifacts = generate_model_split(output_dir)
        return dataclasses.replace(artifacts, probes=artifacts.probes[1:])

    monkeypatch.setattr(
        probe_adequacy, "generate_model_split", without_first_capture
    )

    status, _ = _main(
        tmp_path, monkeypatch, _AnswerRunner(_gold_answers(split))
    )

    assert status == 2
    assert _error_code(capsys) == "capture_missing"


@_POSIX_ONLY
def test_an_unwritable_receipt_path_is_an_io_error(
    split: ModelSplitArtifacts,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "receipts").write_text("a file, not a folder\n", "utf-8")

    status, _ = _main(
        tmp_path, monkeypatch, _AnswerRunner(_gold_answers(split))
    )

    assert status == 2
    assert _error_code(capsys) == "io_error"


def test_an_unsafe_source_revision_is_refused_before_measuring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as caught:
        _main(
            tmp_path, monkeypatch, _AnswerRunner({}), "--source-revision", "a b"
        )

    assert caught.value.code == 2
    assert "source revision" in capsys.readouterr().err
