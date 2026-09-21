"""Docker-only measured comparison of bounded and direct subprocess runners."""

from __future__ import annotations

import argparse
import ast
from dataclasses import asdict
from dataclasses import dataclass
import hashlib
import inspect
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

from dfilterforge import runner as runner_module
from dfilterforge.canonical import content_sha256
from dfilterforge.compiler import compile_intent
from dfilterforge.evaluation import AblationDecision
from dfilterforge.evaluation import AblationReceiptV1
from dfilterforge.evaluation import aggregate_metrics
from dfilterforge.evaluation import ComplexitySnapshotV1
from dfilterforge.evaluation import evaluate_probe
from dfilterforge.evaluation import ProbeResultV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.runner import RunnerError
from dfilterforge.runner import RunnerLimits
from dfilterforge.runner import RunResult
from dfilterforge.runner import TsharkRunner


def _simplified_run(
    executable: Path, capture: Path, display_filter: str
) -> RunResult:
    """Test-only candidate: direct file path and fully buffered subprocess output."""
    capture_hash = hashlib.sha256(capture.read_bytes()).hexdigest()
    completed = subprocess.run(
        [
            str(executable),
            "-n",
            "-r",
            str(capture),
            "-Y",
            display_filter,
            "-T",
            "fields",
            "-e",
            "frame.number",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
        timeout=5,
        shell=False,
        close_fds=True,
        start_new_session=True,
        cwd="/",
        env={
            "PATH": "/opt/wireshark/bin:/usr/bin:/bin",
            "HOME": "/nonexistent",
            "XDG_CONFIG_HOME": "/nonexistent",
            "WIRESHARK_CONFIG_DIR": "/nonexistent",
            "WIRESHARK_PLUGIN_DIR": "/nonexistent",
            "LANG": "C",
            "LC_ALL": "C",
            "TZ": "UTC",
        },
    )
    return RunResult(
        frames=tuple(int(line) for line in completed.stdout.splitlines()),
        runtime_ms=0,
        capture_sha256=capture_hash,
    )


def _simplified_exit_outcome(
    executable: Path, capture: Path, display_filter: str
) -> tuple[int, str, int]:
    """Reproduces the exit-status mapping at revision 1c64140.

    That revision reported one code for every non-zero status, so it could not
    tell a rejected display filter from an unreadable capture. The call is
    identical to the one in _simplified_run except that it does not raise on a
    failure status, because the status is what this witness measures. The third
    returned value counts the frame lines printed before the failure.
    """
    completed = subprocess.run(
        [
            str(executable),
            "-n",
            "-r",
            str(capture),
            "-Y",
            display_filter,
            "-T",
            "fields",
            "-e",
            "frame.number",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=5,
        shell=False,
        close_fds=True,
        start_new_session=True,
        cwd="/",
        env={
            "PATH": "/opt/wireshark/bin:/usr/bin:/bin",
            "HOME": "/nonexistent",
            "XDG_CONFIG_HOME": "/nonexistent",
            "WIRESHARK_CONFIG_DIR": "/nonexistent",
            "WIRESHARK_PLUGIN_DIR": "/nonexistent",
            "LANG": "C",
            "LC_ALL": "C",
            "TZ": "UTC",
        },
    )
    return (
        completed.returncode,
        "accepted" if completed.returncode == 0 else "tshark_failed",
        len(completed.stdout.splitlines()),
    )


@dataclass(frozen=True)
class _Input:
    probe_id: str
    capture: Path
    capture_sha256: str
    filter_kind: str
    display_filter: str
    expected_frames: tuple[int, ...]
    canonical_frames: tuple[int, ...]


def _load_inputs(fixtures: Path) -> tuple[_Input, ...]:
    manifest = json.loads(
        (fixtures / "manifest.json").read_text(encoding="utf-8")
    )
    inputs: list[_Input] = []
    for case in manifest["cases"]:
        spec = SemanticSpecV1.model_validate_json(
            (fixtures / case["spec_path"]).read_bytes(),
        )
        for probe in case["probes"]:
            for kind, display_filter in (
                ("compiled", compile_intent(spec.canonical_ir)),
                ("reference", spec.reference_filter),
                ("near-wrong", case["near_wrong_filter"]),
            ):
                expected = (
                    probe["near_wrong_frames"]
                    if kind == "near-wrong"
                    else probe["expected_frames"]
                )
                inputs.append(
                    _Input(
                        probe_id=probe["probe_id"],
                        capture=(fixtures / probe["capture_path"]).resolve(),
                        capture_sha256=probe["capture_sha256"],
                        filter_kind=kind,
                        display_filter=display_filter,
                        expected_frames=tuple(expected),
                        canonical_frames=tuple(probe["expected_frames"]),
                    )
                )
    return tuple(inputs)


def _measure_pairs(
    runner: TsharkRunner,
    inputs: tuple[_Input, ...],
    repetitions: int,
) -> tuple[
    tuple[ProbeResultV1, ...],
    tuple[ProbeResultV1, ...],
    list[dict[str, object]],
]:
    full_results: list[ProbeResultV1] = []
    simplified_results: list[ProbeResultV1] = []
    rows: list[dict[str, object]] = []
    for repetition in range(repetitions):
        order = (
            ("full", "simplified")
            if repetition % 2 == 0
            else ("simplified", "full")
        )
        for task in inputs:
            results: dict[str, RunResult] = {}
            timings: dict[str, float] = {}
            for variant in order:
                started = time.perf_counter()
                if variant == "full":
                    result = runner.run(task.capture, task.display_filter)
                else:
                    result = _simplified_run(
                        runner.executable_path,
                        task.capture,
                        task.display_filter,
                    )
                timings[variant] = (time.perf_counter() - started) * 1000
                if result.capture_sha256 != task.capture_sha256:
                    raise ValueError(
                        "Fixture capture hash differs from the manifest"
                    )
                results[variant] = result
            sample_id = f"{task.probe_id}-{task.filter_kind}-{repetition}"
            full_results.append(
                evaluate_probe(
                    sample_id,
                    task.expected_frames,
                    results["full"].frames,
                    timings["full"],
                )
            )
            simplified_results.append(
                evaluate_probe(
                    sample_id,
                    task.expected_frames,
                    results["simplified"].frames,
                    timings["simplified"],
                )
            )
            rows.append(
                {
                    "sample_id": sample_id,
                    "order": order,
                    "filter_kind": task.filter_kind,
                    "expected_frames_hash": content_sha256(
                        task.expected_frames
                    ),
                    "full_frames_hash": content_sha256(results["full"].frames),
                    "simplified_frames_hash": content_sha256(
                        results["simplified"].frames
                    ),
                    "frame_sets_equal": results["full"].frames
                    == results["simplified"].frames,
                    "mutation_killed": (
                        results["full"].frames != task.canonical_frames
                        and results["simplified"].frames
                        != task.canonical_frames
                        if task.filter_kind == "near-wrong"
                        else None
                    ),
                    "full_runtime_ms": timings["full"],
                    "simplified_runtime_ms": timings["simplified"],
                }
            )
    return tuple(full_results), tuple(simplified_results), rows


def _safety_witness(scratch_parent: Path, capture: Path) -> dict[str, object]:
    """Uses finite 3893-byte output to expose the missing streaming byte cap."""
    with tempfile.TemporaryDirectory(
        prefix="runner-ablation-", dir=scratch_parent
    ) as temporary:
        executable = Path(temporary) / "finite-tshark"
        executable.write_text(
            f"#!{sys.executable}\n"
            "import sys\n"
            "if '--version' in sys.argv:\n"
            "    print('TShark (Wireshark) 4.6.8')\n"
            "else:\n"
            "    print('\\n'.join(str(frame) for frame in range(1, 1001)))\n",
            encoding="utf-8",
        )
        executable.chmod(0o700)
        full = TsharkRunner(str(executable), RunnerLimits(max_stdout_bytes=128))
        full.version()
        full_outcome = "accepted"
        try:
            full.run(capture, "tcp")
        except RunnerError as error:
            full_outcome = error.code
        simplified = _simplified_run(executable, capture, "tcp")
        return {
            "name": "finite-stdout-limit-witness",
            "configured_stdout_limit_bytes": 128,
            "generated_stdout_bytes": len(
                "".join(f"{frame}\n" for frame in range(1, 1001)).encode()
            ),
            "full_outcome": full_outcome,
            "simplified_outcome": "accepted",
            "simplified_frame_count": len(simplified.frames),
            "simplification_preserves_safety": full_outcome != "output_limit",
            "scope": "A finite output-cap witness, not a complete isolation audit.",
        }


def _exit_status_witnesses(
    runner: TsharkRunner, capture: Path, scratch_parent: Path
) -> list[dict[str, object]]:
    """Measures how each variant classifies real tshark failure statuses.

    Every witness must fail, so a row that returns zero raises rather than
    quietly weakening the evidence. Each row also records how many frame lines
    tshark printed before failing, which is what the bounded runner discards
    instead of returning a short result. Only the capture basename is recorded;
    the derived captures live in a temporary directory that this call removes.
    """
    with tempfile.TemporaryDirectory(
        prefix="runner-exit-status-", dir=scratch_parent
    ) as temporary:
        data = capture.read_bytes()
        truncated = Path(temporary) / "truncated.pcap"
        truncated.write_bytes(data[: len(data) // 2 + 7])
        garbage = Path(temporary) / "garbage.pcap"
        garbage.write_bytes(b"this is not a capture file\n" * 20)
        witnesses = (
            ("filter", "ip.ttll", capture),
            ("filter", "tcp &&", capture),
            ("filter", 'ip.ttl <= "abc"', capture),
            ("capture", "tcp", truncated),
            ("capture", "tcp", garbage),
            ("filter", "ip.ttll", garbage),
        )
        rows: list[dict[str, object]] = []
        for kind, display_filter, path in witnesses:
            full = "accepted"
            try:
                runner.run(path, display_filter)
            except RunnerError as error:
                full = error.code
            returncode, simplified, stdout_frames = _simplified_exit_outcome(
                runner.executable_path, path, display_filter
            )
            if returncode == 0:
                raise ValueError(
                    "An exit-status witness unexpectedly succeeded"
                )
            rows.append(
                {
                    "kind": kind,
                    "display_filter": display_filter,
                    "capture": path.name,
                    "returncode": returncode,
                    "stdout_frames": stdout_frames,
                    "full": full,
                    "simplified": simplified,
                }
            )
        return rows


def _complexity(source: str) -> dict[str, int]:
    tree = ast.parse(source)
    public_symbols = sum(
        isinstance(node, (ast.FunctionDef, ast.ClassDef))
        and not node.name.startswith("_")
        for node in tree.body
    )
    return {
        "source_lines": len(source.splitlines()),
        "public_symbols": public_symbols,
    }


def _environment_manifest(
    runner: TsharkRunner,
    runner_source_sha256: str,
) -> dict[str, object]:
    """Records the measured process environment for this limited experiment."""
    return {
        "tshark_version": runner.version(),
        "tshark_executable_sha256": hashlib.sha256(
            runner.executable_path.read_bytes(),
        ).hexdigest(),
        "runner_source_sha256": runner_source_sha256,
        "runner_limits": asdict(runner.limits),
        "python_version": sys.version,
        "platform": platform.platform(),
        "timezone": "UTC",
        "name_resolution": False,
        "pass_mode": "single",
        "scope": (
            "Nine synthetic pilot captures and one finite output-limit witness. "
            "This records executable/process identity; the caller must record "
            "the enclosing Docker image ID separately. It is not a complete "
            "isolation or pilot-scale gate measurement."
        ),
    }


def main() -> int:
    """Runs the measured ablation and writes both evidence and a typed receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--code-revision", default="working-tree")
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 20:
        parser.error("--repetitions must be between 1 and 20")
    inputs = _load_inputs(args.fixtures)
    if not inputs:
        parser.error("--fixtures must contain at least one probe")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    runner = TsharkRunner()
    version = runner.version()
    # Warm both paths before alternating paired measurements.
    runner.run(inputs[0].capture, inputs[0].display_filter)
    _simplified_run(
        runner.executable_path, inputs[0].capture, inputs[0].display_filter
    )
    full, simplified, rows = _measure_pairs(runner, inputs, args.repetitions)
    safety = _safety_witness(args.output.parent, inputs[0].capture)
    exit_status = _exit_status_witnesses(
        runner, inputs[0].capture, args.output.parent
    )
    full_source = inspect.getsource(runner_module)
    simplified_source = inspect.getsource(_simplified_run)
    full_source_hash = hashlib.sha256(full_source.encode()).hexdigest()
    environment = _environment_manifest(runner, full_source_hash)
    fixture_manifest_hash = hashlib.sha256(
        (args.fixtures / "manifest.json").read_bytes(),
    ).hexdigest()
    full_complexity = _complexity(full_source)
    simplified_complexity = _complexity(simplified_source)
    full_metrics = aggregate_metrics(full)
    simplified_metrics = aggregate_metrics(simplified)
    if not all(probe.exact for probe in full):
        decision = AblationDecision.INCONCLUSIVE
        rationale = (
            "The protected implementation did not match all authored labels."
        )
    elif not safety["simplification_preserves_safety"]:
        decision = AblationDecision.KEEP_PROTECTED
        rationale = (
            "Direct subprocess buffering accepts output above the configured cap. "
            "The finite safety witness prevents adopting the simpler candidate, "
            "independently of latency. Equivalence is limited to nine pilot captures."
        )
    else:
        decision = AblationDecision.INCONCLUSIVE
        rationale = "The expected safety difference was not reproduced; investigate the witness."
    receipt = AblationReceiptV1(
        ablation_id="001-bounded-tshark-runner",
        hypothesis="Direct subprocess buffering preserves the bounded runner's behavior and safety.",
        full_revision=args.code_revision,
        simplified_patch_hash=hashlib.sha256(
            simplified_source.encode()
        ).hexdigest(),
        input_hashes=tuple(
            sorted(
                {task.capture_sha256 for task in inputs}
                | {fixture_manifest_hash},
            )
        ),
        full_metrics=full_metrics,
        simplified_metrics=simplified_metrics,
        full_complexity=ComplexitySnapshotV1(
            module_count=1,
            dependency_count=0,
            public_symbol_count=full_complexity["public_symbols"],
        ),
        simplified_complexity=ComplexitySnapshotV1(
            module_count=1,
            dependency_count=0,
            public_symbol_count=simplified_complexity["public_symbols"],
        ),
        decision=decision,
        rationale=rationale,
    )
    payload = {
        "schema_version": "1.0",
        "receipt": receipt.model_dump(mode="json"),
        "tshark_version": version,
        "repetitions": args.repetitions,
        "environment": environment,
        "environment_hash": content_sha256(environment),
        "fixture_manifest_sha256": fixture_manifest_hash,
        "full_script_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "sample_count_per_variant": len(full),
        "timing_scope": "End-to-end call including capture hashing; cached version check after warmup.",
        "sources": {
            "full_sha256": full_source_hash,
            "simplified_sha256": hashlib.sha256(
                simplified_source.encode()
            ).hexdigest(),
            "full": full_complexity,
            "simplified": simplified_complexity,
            "additional_third_party_dependencies": 0,
        },
        "correctness": {
            "all_full_labels_match": all(probe.exact for probe in full),
            "all_simplified_labels_match": all(
                probe.exact for probe in simplified
            ),
            "all_paired_frame_sets_equal": all(
                row["frame_sets_equal"] for row in rows
            ),
            "mutation_samples": sum(
                row["filter_kind"] == "near-wrong" for row in rows
            ),
            "mutation_kills": sum(
                row["mutation_killed"] is True for row in rows
            ),
            "pilot_scale_gate_verified": False,
        },
        "safety_witness": safety,
        "exit_status_witnesses": exit_status,
        "full_separates_filter_from_capture": not (
            {row["full"] for row in exit_status if row["kind"] == "filter"}
            & {row["full"] for row in exit_status if row["kind"] == "capture"}
        ),
        "paired_samples": rows,
    }
    args.output.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    receipt_path = args.output.with_suffix(".receipt.json")
    receipt_path.write_text(
        receipt.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "receipt": str(receipt_path),
                "decision": decision,
            }
        )
    )
    success = (
        decision != AblationDecision.INCONCLUSIVE
        and all(probe.exact for probe in full)
        and all(probe.exact for probe in simplified)
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
