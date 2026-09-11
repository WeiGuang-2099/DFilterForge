"""Tests for CLI JSON contracts."""

import json
from pathlib import Path

import pytest

from dfilterforge.cli import main


def _intent_payload() -> dict[str, object]:
    return {
        "expression": {
            "kind": "predicate",
            "field": "tcp",
            "operator": "exists",
        }
    }


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _evaluation_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    intent_path = tmp_path / "candidate.json"
    spec_path = tmp_path / "spec.json"
    observations_path = tmp_path / "observations.json"
    environment_path = tmp_path / "environment.json"
    _write_json(intent_path, _intent_payload())
    _write_json(
        spec_path,
        {
            "task_id": "tcp-v1",
            "intent": "Show TCP packets.",
            "canonical_ir": _intent_payload(),
            "reference_filter": "tcp",
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


def test_generate_fails_closed_without_model_backend(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        ["generate", "--intent", "show tcp", "--pipeline", "prompt"]
    )

    error = json.loads(capsys.readouterr().err)
    assert exit_code == 2
    assert error["error"]["code"] == "model_backend_unavailable"


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
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    intent_path, spec_path, observations_path, environment_path = (
        _evaluation_inputs(tmp_path)
    )
    receipt_path = tmp_path / "receipt.json"

    evaluate_code = main(
        [
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
    )
    benchmark_code = main(["benchmark", "run", "--receipts", str(receipt_path)])
    benchmark_output = json.loads(capsys.readouterr().out)

    assert evaluate_code == 0
    assert benchmark_code == 0
    assert benchmark_output["receipt_count"] == 1
    assert benchmark_output["receipts"][0]["metrics"]["strong_exact_count"] == 1


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
