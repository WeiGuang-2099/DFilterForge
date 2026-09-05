"""End-to-end CLI tests using the pinned Docker tshark executable."""

import hashlib
import json
from pathlib import Path

import pytest

from dfilterforge.canonical import content_sha256
from dfilterforge.cli import main
from dfilterforge.evaluation import EvaluationReceiptV1
from dfilterforge.fixtures import generate_fixtures
from dfilterforge.live import LiveEnvironmentV1
from dfilterforge.runner import TsharkRunner

_CASES = ("tcp-syn-no-ack", "dns-udp-query", "udp-destination-53")


def _live_args(root: Path, case: str) -> list[str]:
    return [
        "evaluate-live",
        "--spec",
        str(root / "specs" / f"{case}.json"),
        "--candidate-ir",
        str(root / "intents" / f"{case}.json"),
        "--capture-root",
        str(root / "captures"),
        "--run-id",
        "integration",
        "--created-at",
        "2026-09-04T00:00:00Z",
        "--code-revision",
        "integration-test",
    ]


def test_doctor_verifies_actual_pinned_executable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # No skip: the test image must supply the pinned executable.
    assert main(["doctor"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["tshark"]["version"] == "4.6.8"
    assert report["tshark"]["version_ok"] is True
    assert main(["doctor", "--require-tshark-version", "4.6"]) == 2
    assert json.loads(capsys.readouterr().out)["tshark"]["version_ok"] is False


def test_fixture_generate_command_writes_manifest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["fixtures", "generate", "--output-dir", str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert Path(report["manifest_path"]).is_file()
    assert len(list((tmp_path / "captures").glob("*.pcap"))) == 9


@pytest.mark.parametrize("case", _CASES)
def test_live_cli_executes_three_curated_cases_and_writes_replayable_receipt(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    generate_fixtures(tmp_path)
    output = tmp_path / "receipt.json"
    assert main([*_live_args(tmp_path, case), "--output", str(output)]) == 0
    summary = json.loads(capsys.readouterr().out)
    receipt = EvaluationReceiptV1.model_validate_json(output.read_text())
    environment = LiveEnvironmentV1.model_validate_json(
        (tmp_path / "receipt.environment.json").read_text()
    )
    assert receipt.metrics.strong_exact_count == 3
    assert receipt.metrics.macro_f1 == 1
    assert all(probe.runtime_ms > 0 for probe in receipt.probes)
    assert receipt.environment_hash == environment.environment_hash()
    assert summary["receipt_hash"] == receipt.receipt_hash()
    assert (
        environment.executable_sha256
        == hashlib.sha256(
            TsharkRunner().executable_path.read_bytes()
        ).hexdigest()
    )
    assert (
        main(
            [
                "replay-run",
                "--receipt",
                str(output),
                "--environment-hash",
                environment.environment_hash(),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["validated"] is True


def test_live_repeat_has_stable_packet_sets(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    generate_fixtures(tmp_path)
    args = _live_args(tmp_path, _CASES[0])
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(args) == 0
    second = json.loads(capsys.readouterr().out)
    assert first["packet_set_hash"] == second["packet_set_hash"]
    assert first["environment_hash"] == second["environment_hash"]
    assert content_sha256(first["environment"]) == first["environment_hash"]


def test_live_near_wrong_candidate_keeps_packet_differences(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    generate_fixtures(tmp_path)
    candidate = tmp_path / "intents" / "tcp-syn-no-ack.json"
    candidate.write_text(
        json.dumps(
            {
                "expression": {
                    "kind": "predicate",
                    "field": "tcp.flags.syn",
                    "operator": "eq",
                    "value": True,
                }
            }
        ),
        encoding="utf-8",
    )
    assert main(_live_args(tmp_path, "tcp-syn-no-ack")) == 0
    result = json.loads(capsys.readouterr().out)
    receipt = result["receipt"]
    assert receipt["metrics"]["strong_exact_count"] == 0
    assert all(probe["candidate_only"] for probe in receipt["probes"])


def test_live_missing_executable_is_machine_readable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    generate_fixtures(tmp_path)
    assert (
        main(
            [
                *_live_args(tmp_path, _CASES[0]),
                "--tshark",
                "definitely-not-tshark",
            ]
        )
        == 2
    )
    result = json.loads(capsys.readouterr().err)
    assert result["error"]["code"]
    assert "definitely-not-tshark" not in result["error"]["message"]


def test_invalid_candidate_does_not_log_private_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    generate_fixtures(tmp_path)
    candidate = tmp_path / "intents" / "tcp-syn-no-ack.json"
    private_value = "private-packet-payload-should-not-appear"
    candidate.write_text(
        json.dumps({"expression": private_value}), encoding="utf-8"
    )
    assert main(_live_args(tmp_path, "tcp-syn-no-ack")) == 2
    stderr = capsys.readouterr().err
    assert private_value not in stderr
    assert json.loads(stderr)["error"]["code"] == "schema_invalid"


def test_non_utf8_json_input_returns_sanitized_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate = tmp_path / "private-input.json"
    candidate.write_bytes(b"\xffprivate-packet-payload")
    assert main(["compile", "--intent-ir", str(candidate)]) == 2
    stderr = capsys.readouterr().err
    assert "private" not in stderr
    assert json.loads(stderr)["error"]["code"] == "input_invalid"


def test_nul_json_path_returns_sanitized_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["compile", "--intent-ir", "\x00private-path.json"]) == 2
    stderr = capsys.readouterr().err
    assert "private" not in stderr
    assert json.loads(stderr)["error"]["code"] == "input_invalid"
