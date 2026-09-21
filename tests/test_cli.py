"""Tests for CLI JSON contracts."""

from collections.abc import Callable
from datetime import datetime
from datetime import timezone
import json
from pathlib import Path
from typing import Any, cast

import pytest

from dfilterforge import cli as cli_module
from dfilterforge.cli import build_parser
from dfilterforge.cli import CliError
from dfilterforge.cli import main
from dfilterforge.compiler import compile_intent
from dfilterforge.compiler import CompileError
from dfilterforge.errors import DFilterForgeError
from dfilterforge.evaluation import aggregate_metrics
from dfilterforge.evaluation import evaluate_probe
from dfilterforge.evaluation import EvaluationReceiptV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.field_catalog import CatalogError
from dfilterforge.field_catalog import FieldCatalogV1
from dfilterforge.field_catalog import FieldDefinition
from dfilterforge.field_catalog import FieldType
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.live import LiveEnvironmentV1
from dfilterforge.live import LiveError
from dfilterforge.replay import ExecutableReplayResultV1
from dfilterforge.replay import ReplayError
from dfilterforge.replay import ReplayProbeResultV1
from dfilterforge.runner import RunnerError
from dfilterforge.runner import TsharkRunner
from dfilterforge.scoring import ScoreReportV1
from dfilterforge.scoring import ScoringError

_TCP = FieldDefinition(
    abbreviation="tcp",
    field_type=FieldType.PROTOCOL,
    protocol="tcp",
    display_name="Transmission Control Protocol",
)
_IP_SRC = FieldDefinition(
    abbreviation="ip.src",
    field_type=FieldType.IPV4,
    protocol="ip",
    display_name="Source Address",
)


def _intent_payload(
    field: str = "tcp", operator: str = "exists", value: object = None
) -> dict[str, object]:
    expression: dict[str, object] = {
        "kind": "predicate",
        "field": field,
        "operator": operator,
    }
    if value is not None:
        expression["value"] = value
    return {"expression": expression}


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _install_fake_catalog(
    monkeypatch: pytest.MonkeyPatch, *fields: FieldDefinition
) -> tuple[FieldCatalogV1, list[tuple[IntentIrV1, ...]]]:
    """Binds a fixed catalog in place of the Docker-only frozen inventory."""
    bound = FieldCatalogV1(
        tshark_version="4.6.8", profile_hash="profile", fields=fields
    )
    calls: list[tuple[IntentIrV1, ...]] = []

    def fake_bind_catalog(
        runner: TsharkRunner,
        intents: tuple[IntentIrV1, ...],
        supplied: FieldCatalogV1 | None = None,
    ) -> FieldCatalogV1:
        del runner, supplied
        calls.append(intents)
        return bound

    monkeypatch.setattr(cli_module, "bind_catalog", fake_bind_catalog)
    return bound, calls


def _evaluation_inputs(
    tmp_path: Path,
    *,
    intent: dict[str, object] | None = None,
    reference_filter: str = "tcp",
) -> tuple[Path, Path, Path, Path]:
    candidate = _intent_payload() if intent is None else intent
    intent_path = tmp_path / "candidate.json"
    spec_path = tmp_path / "spec.json"
    observations_path = tmp_path / "observations.json"
    environment_path = tmp_path / "environment.json"
    _write_json(intent_path, candidate)
    _write_json(
        spec_path,
        {
            "task_id": "tcp-v1",
            "intent": "Show TCP packets.",
            "canonical_ir": candidate,
            "reference_filter": reference_filter,
            "probes": [
                {
                    "probe_id": "probe-a",
                    "capture_sha256": "capture",
                    "expected_frames": [1, 3],
                }
            ],
            "split": "test",
            "provenance": "generated",
            "license": "CC-BY-4.0",
            "review_status": "reviewed",
        },
    )
    _write_json(
        observations_path,
        {"probe-a": {"candidate_frames": [1, 3], "runtime_ms": 12.5}},
    )
    _write_json(
        environment_path,
        {
            "tshark_version": "4.6.8",
            "image_digest": "sha256:image",
            "profile_hash": "profile",
            "catalog_hash": "catalog",
        },
    )
    return intent_path, spec_path, observations_path, environment_path


def _evaluate_args(
    inputs: tuple[Path, Path, Path, Path], receipt_path: Path
) -> list[str]:
    intent_path, spec_path, observations_path, environment_path = inputs
    return [
        "evaluate",
        "--spec",
        str(spec_path),
        "--candidate-ir",
        str(intent_path),
        "--observations",
        str(observations_path),
        "--environment",
        str(environment_path),
        "--run-id",
        "run-1",
        "--created-at",
        "2026-09-02T00:00:00Z",
        "--code-revision",
        "abc123",
        "--output",
        str(receipt_path),
    ]


def test_compile_command_prints_machine_readable_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    intent_path = tmp_path / "intent.json"
    intent_path.write_text(
        json.dumps(_intent_payload()),
        encoding="utf-8",
    )

    exit_code = main(["compile", "--intent-ir", str(intent_path)])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["display_filter"] == "tcp"
    assert len(output["intent_hash"]) == 64


def test_invalid_intent_reports_schema_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    intent_path = tmp_path / "intent.json"
    intent_path.write_text("{}", encoding="utf-8")

    exit_code = main(["compile", "--intent-ir", str(intent_path)])

    error = json.loads(capsys.readouterr().err)
    assert exit_code == 2
    assert error["error"]["code"] == "schema_invalid"


def test_doctor_reports_missing_tshark(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["doctor", "--tshark", "definitely-not-tshark"])

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert result["tshark"]["available"] is False


def test_compile_rejects_catalog_built_for_another_profile(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fields_path = tmp_path / "fields.tsv"
    values_path = tmp_path / "values.tsv"
    catalog_path = tmp_path / "catalog.json"
    intent_path = tmp_path / "intent.json"
    fields_path.write_text(
        "P\tTransmission Control Protocol\ttcp\n"
        "F\tDestination Port\ttcp.dstport\tFT_UINT16\ttcp\tBASE_DEC\n",
        encoding="utf-8",
    )
    values_path.write_text("V\ttcp.dstport\t443\tHTTPS\n", encoding="utf-8")
    _write_json(intent_path, _intent_payload())

    exit_code = main(
        [
            "catalog",
            "build",
            "--fields-tsv",
            str(fields_path),
            "--values-tsv",
            str(values_path),
            "--tshark-version",
            "4.6.8",
            "--profile-hash",
            "profile",
            "--output",
            str(catalog_path),
        ]
    )
    compile_code = main(
        [
            "compile",
            "--intent-ir",
            str(intent_path),
            "--catalog",
            str(catalog_path),
        ]
    )

    output = json.loads(capsys.readouterr().err)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert compile_code == 2
    assert len(catalog["catalog_hash"]) == 64
    assert output["error"]["code"] == "catalog_profile_mismatch"


def test_compile_checks_profile_before_catalog_projection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    intent_path = tmp_path / "intent.json"
    catalog_path = tmp_path / "catalog.json"
    _write_json(intent_path, _intent_payload())
    _write_json(
        catalog_path,
        {
            "tshark_version": "4.6.8",
            "profile_hash": "profile",
            "fields": [],
        },
    )

    exit_code = main(
        [
            "compile",
            "--intent-ir",
            str(intent_path),
            "--catalog",
            str(catalog_path),
        ]
    )

    error = json.loads(capsys.readouterr().err)
    assert exit_code == 2
    assert error["error"]["code"] == "catalog_profile_mismatch"


def test_spec_validate_returns_content_hash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, spec_path, _, _ = _evaluation_inputs(tmp_path)

    exit_code = main(["spec", "validate", "--spec", str(spec_path)])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert len(output["spec_hash"]) == 64


def test_evaluate_and_benchmark_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_fake_catalog(monkeypatch, _TCP)
    receipt_path = tmp_path / "receipt.json"

    evaluate_code = main(
        _evaluate_args(_evaluation_inputs(tmp_path), receipt_path)
    )
    benchmark_code = main(["benchmark", "run", "--receipts", str(receipt_path)])
    benchmark_output = json.loads(capsys.readouterr().out)

    assert evaluate_code == 0
    assert benchmark_code == 0
    assert benchmark_output["receipt_count"] == 1
    assert benchmark_output["receipts"][0]["metrics"]["strong_exact_count"] == 1


def test_evaluate_compiles_candidate_through_bound_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An offline receipt must hold the text replay recompiles with a catalog."""
    bound, calls = _install_fake_catalog(monkeypatch, _IP_SRC)
    payload = _intent_payload("ip.src", "eq", "192.0.2.1")
    candidate_ir = IntentIrV1.model_validate(payload)
    receipt_path = tmp_path / "receipt.json"

    exit_code = main(
        _evaluate_args(
            _evaluation_inputs(
                tmp_path,
                intent=payload,
                reference_filter="ip.src == 192.0.2.1",
            ),
            receipt_path,
        )
    )

    receipt = EvaluationReceiptV1.model_validate_json(
        receipt_path.read_text(encoding="utf-8")
    )
    assert exit_code == 0
    assert calls == [(candidate_ir, candidate_ir)]
    assert receipt.candidate_filter == "ip.src == 192.0.2.1"
    assert receipt.candidate_filter == compile_intent(candidate_ir, bound)
    assert receipt.candidate_filter != compile_intent(candidate_ir)


def test_ablation_manifest_is_validated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest_path = tmp_path / "ablation.json"
    metrics = {
        "probe_count": 1,
        "strong_exact_count": 1,
        "empty_set_coincidence_count": 0,
        "macro_precision": 1,
        "macro_recall": 1,
        "macro_f1": 1,
        "macro_jaccard": 1,
        "p50_runtime_ms": 1,
        "p95_runtime_ms": 1,
    }
    complexity = {
        "module_count": 1,
        "dependency_count": 1,
        "public_symbol_count": 1,
    }
    _write_json(
        manifest_path,
        {
            "ablation_id": "slice-1",
            "hypothesis": "A function is sufficient.",
            "full_revision": "abc",
            "simplified_patch_hash": "def",
            "input_hashes": ["input"],
            "full_metrics": metrics,
            "simplified_metrics": metrics,
            "full_complexity": complexity,
            "simplified_complexity": complexity,
            "decision": "keep_simplified",
            "rationale": "Behavior is unchanged with fewer symbols.",
        },
    )

    exit_code = main(["ablation", "run", "--manifest", str(manifest_path)])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["decision"] == "keep_simplified"


@pytest.mark.parametrize(
    ("error_type", "builtin_base"),
    [
        (CliError, RuntimeError),
        (CompileError, ValueError),
        (CatalogError, ValueError),
        (LiveError, RuntimeError),
        (ReplayError, RuntimeError),
        (RunnerError, RuntimeError),
    ],
)
def test_boundary_errors_share_one_base_and_keep_builtin_bases(
    error_type: type[DFilterForgeError], builtin_base: type[Exception]
) -> None:
    error = error_type("some_code", "safe message")

    assert isinstance(error, DFilterForgeError)
    assert isinstance(error, builtin_base)
    assert error.code == "some_code"
    assert str(error) == "safe message"


def _replay_receipt(tmp_path: Path) -> Path:
    """Writes a receipt whose candidate filter is the only model text."""
    probe = evaluate_probe("probe-a", (1, 3), (1, 3), 12.5)
    receipt = EvaluationReceiptV1(
        run_id="run-1",
        created_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        code_revision="abc123",
        environment_hash="recorded-environment",
        data_hash="recorded-data",
        candidate_filter="tcp.flags.syn == 1",
        reference_filter="tcp",
        probes=(probe,),
        metrics=aggregate_metrics((probe,)),
    )
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(receipt.model_dump_json(), encoding="utf-8")
    return receipt_path


def _replay_args(tmp_path: Path, *candidate: str) -> list[str]:
    return [
        "replay-run",
        "--receipt",
        str(tmp_path / "receipt.json"),
        "--spec",
        str(tmp_path / "spec.json"),
        "--capture-root",
        str(tmp_path / "captures"),
        *candidate,
    ]


@pytest.mark.parametrize(
    ("candidate_arguments", "parses"),
    [
        (["--candidate-ir", "candidate.json", "--receipt-filter"], False),
        ([], False),
        (["--receipt-filter"], True),
    ],
)
def test_replay_run_requires_exactly_one_candidate_source(
    tmp_path: Path, candidate_arguments: list[str], parses: bool
) -> None:
    argv = _replay_args(tmp_path, *candidate_arguments)

    if parses:
        arguments = build_parser().parse_args(argv)
        assert arguments.receipt_filter is True
        assert arguments.candidate_ir is None
        return
    with pytest.raises(SystemExit) as caught:
        build_parser().parse_args(argv)
    assert caught.value.code == 2


def test_replay_run_receipt_filter_passes_the_recorded_string(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The model's text is read from the receipt, never from the argv."""
    _evaluation_inputs(tmp_path)
    receipt_path = _replay_receipt(tmp_path)
    receipt = EvaluationReceiptV1.model_validate_json(
        receipt_path.read_text(encoding="utf-8")
    )
    loaded: list[Path] = []
    load_model = cast(
        Callable[[Path, type[Any]], Any],
        getattr(cli_module, "_load_model"),
    )

    def counting_load(path: Path, model_type: type[Any]) -> Any:
        loaded.append(path)
        return load_model(path, model_type)

    monkeypatch.setattr(cli_module, "_load_model", counting_load)
    recorded: list[IntentIrV1 | str] = []
    replay_probe = ReplayProbeResultV1(
        probe_id="probe-a",
        recorded_frames=(1, 3),
        replayed_frames=(1, 3),
        runtime_ms=9,
        exact=True,
    )
    replay_result = ExecutableReplayResultV1(
        run_id="run-1", exact=True, probes=(replay_probe,)
    )
    environment = LiveEnvironmentV1(
        tshark_version="4.6.8",
        executable_sha256="measured",
        runner_source_sha256="measured",
        runner_limits_hash="measured",
        catalog_hash="measured",
        python_version="3.12.3",
        platform_machine="x86_64",
    )

    def fake_replay_live(
        receipt: EvaluationReceiptV1,
        spec: SemanticSpecV1,
        candidate: IntentIrV1 | str,
        capture_root: Path,
        *,
        catalog: FieldCatalogV1 | None = None,
        runner: TsharkRunner | None = None,
    ) -> tuple[ExecutableReplayResultV1, LiveEnvironmentV1]:
        del receipt, spec, capture_root, catalog, runner
        recorded.append(candidate)
        return replay_result, environment

    monkeypatch.setattr(cli_module, "replay_live", fake_replay_live)

    exit_code = main(_replay_args(tmp_path, "--receipt-filter"))

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert recorded == [receipt.candidate_filter]
    assert recorded == ["tcp.flags.syn == 1"]
    assert loaded == [receipt_path, tmp_path / "spec.json"]
    assert output["replay"]["trace"] is None


def _score_args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "score",
        "--run-dir",
        str(tmp_path / "dev-0001"),
        "--code-revision",
        "test",
        *extra,
    ]


def _score_report(
    tmp_path: Path, differences: tuple[str, ...] = ()
) -> ScoreReportV1:
    """Builds the report one scoring pass would have returned."""
    return ScoreReportV1(
        output_dir=tmp_path / "scored",
        checked=True,
        items=16,
        outcomes={"strong_exact": 16},
        summary_sha256="0" * 64,
        differences=differences,
    )


def test_score_exit_code_follows_check_differences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A clean check exits 0; a named difference exits 1 and is printed."""
    reports = [
        _score_report(tmp_path),
        _score_report(tmp_path, ("outcomes:C1/mei-0003",)),
    ]

    def fake_score_run(run_dir: Path, **keywords: Any) -> ScoreReportV1:
        del run_dir, keywords
        return reports.pop(0)

    monkeypatch.setattr(cli_module, "score_run", fake_score_run)

    clean = main(_score_args(tmp_path, "--check"))
    first = json.loads(capsys.readouterr().out)
    drifted = main(_score_args(tmp_path, "--check"))
    second = json.loads(capsys.readouterr().out)

    assert clean == 0
    assert first["checked"] is True
    assert first["items"] == 16
    assert first["differences"] == []
    assert drifted == 1
    assert second["differences"] == ["outcomes:C1/mei-0003"]


def test_score_errors_use_the_json_error_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A scoring failure exits 2 behind the shared error envelope."""

    def fake_score_run(run_dir: Path, **keywords: Any) -> ScoreReportV1:
        del run_dir, keywords
        raise ScoringError("prompt_mismatch", "C1 mei-0003")

    monkeypatch.setattr(cli_module, "score_run", fake_score_run)

    exit_code = main(_score_args(tmp_path))

    streams = capsys.readouterr()
    error = json.loads(streams.err)["error"]
    assert exit_code == 2
    assert error["code"] == "prompt_mismatch"
    assert error["message"] == "C1 mei-0003"
    assert streams.out == ""


@pytest.mark.parametrize(
    "arguments",
    [[], ["--run-dir", "run"], ["--code-revision", "test"]],
)
def test_score_requires_run_dir_and_code_revision(
    arguments: list[str],
) -> None:
    """Both identity arguments are required by the parser itself."""
    with pytest.raises(SystemExit) as caught:
        main(["score", *arguments])

    assert caught.value.code == 2


def test_score_passes_the_tshark_path_through(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The requested executable reaches the runner the whole pass shares."""
    built: list[str] = []
    shared: list[object] = []

    def fake_tshark_runner(*, tshark: str) -> TsharkRunner:
        built.append(tshark)
        return TsharkRunner(tshark=tshark)

    def fake_score_run(
        run_dir: Path, *, runner: TsharkRunner, **keywords: Any
    ) -> ScoreReportV1:
        del run_dir, keywords
        shared.append(runner)
        return _score_report(tmp_path)

    monkeypatch.setattr(cli_module, "TsharkRunner", fake_tshark_runner)
    monkeypatch.setattr(cli_module, "score_run", fake_score_run)

    exit_code = main(_score_args(tmp_path, "--tshark", "/usr/bin/true"))

    capsys.readouterr()
    assert exit_code == 0
    assert built == ["/usr/bin/true"]
    assert len(shared) == 1
    assert isinstance(shared[0], TsharkRunner)
