"""Command-line interface for deterministic core workflows."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import cast, TypeVar

from pydantic import BaseModel
from pydantic import ValidationError

from dfilterforge import __version__
from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import content_sha256
from dfilterforge.compiler import compile_intent
from dfilterforge.compiler import CompileError
from dfilterforge.evaluation import AblationReceiptV1
from dfilterforge.evaluation import aggregate_metrics
from dfilterforge.evaluation import EnvironmentManifestV1
from dfilterforge.evaluation import evaluate_probe
from dfilterforge.evaluation import EvaluationReceiptV1
from dfilterforge.evaluation import ProbeResultV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.field_catalog import apply_enum_values
from dfilterforge.field_catalog import CatalogError
from dfilterforge.field_catalog import FieldCatalogV1
from dfilterforge.field_catalog import parse_tshark_fields
from dfilterforge.field_catalog import parse_tshark_values
from dfilterforge.intent_ir import IntentIrV1

JsonObject = dict[str, object]
Command = Callable[[argparse.Namespace], object]
ModelT = TypeVar("ModelT", bound=BaseModel)


class CliError(RuntimeError):
    """A user-facing error with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _read_json(path: Path) -> object:
    try:
        with path.open("r", encoding="utf-8") as source:
            return json.load(source)
    except (OSError, json.JSONDecodeError) as error:
        raise CliError(
            "input_invalid", f"Cannot read {path}: {error}"
        ) from error


def _write_json(value: object, output: Path | None) -> None:
    text = canonical_json(value)
    if output is None:
        print(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"{text}\n", encoding="utf-8")


def _load_model(path: Path, model_type: type[ModelT]) -> ModelT:
    try:
        return model_type.model_validate(_read_json(path))
    except ValidationError as error:
        raise CliError("schema_invalid", str(error)) from error


def _doctor(arguments: argparse.Namespace) -> object:
    tshark_status: JsonObject
    try:
        completed = subprocess.run(
            [arguments.tshark, "--version"],
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=5,
        )
        first_line = (completed.stdout or completed.stderr).splitlines()[0]
        version_ok = (
            completed.returncode == 0
            and arguments.require_tshark_version in first_line
        )
        tshark_status = {
            "available": completed.returncode == 0,
            "required_version": arguments.require_tshark_version,
            "version_line": first_line,
            "version_ok": version_ok,
        }
    except (FileNotFoundError, subprocess.TimeoutExpired, IndexError) as error:
        tshark_status = {
            "available": False,
            "error": type(error).__name__,
            "required_version": arguments.require_tshark_version,
            "version_ok": False,
        }
    return {
        "dfilterforge_version": __version__,
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "tshark": tshark_status,
    }


def _catalog_build(arguments: argparse.Namespace) -> None:
    try:
        field_lines = arguments.fields_tsv.read_text(
            encoding="utf-8"
        ).splitlines()
        fields = parse_tshark_fields(field_lines)
        if arguments.values_tsv is not None:
            value_lines = arguments.values_tsv.read_text(
                encoding="utf-8"
            ).splitlines()
            fields = apply_enum_values(fields, parse_tshark_values(value_lines))
    except OSError as error:
        raise CliError("input_invalid", str(error)) from error
    catalog = FieldCatalogV1(
        tshark_version=arguments.tshark_version,
        profile_hash=arguments.profile_hash,
        fields=fields,
    )
    payload = catalog.model_dump(mode="json")
    payload["catalog_hash"] = catalog.compute_hash()
    validated = FieldCatalogV1.model_validate(payload)
    _write_json(validated, arguments.output)


def _compile(arguments: argparse.Namespace) -> object:
    intent = _load_model(arguments.intent_ir, IntentIrV1)
    catalog: FieldCatalogV1 | None = None
    if arguments.catalog is not None:
        catalog = _load_model(arguments.catalog, FieldCatalogV1)
    return {
        "display_filter": compile_intent(intent, catalog),
        "intent_hash": content_sha256(intent),
    }


def _spec_validate(arguments: argparse.Namespace) -> object:
    spec = _load_model(arguments.spec, SemanticSpecV1)
    return {
        "schema_version": spec.schema_version,
        "spec_hash": content_sha256(spec),
    }


def _generate(arguments: argparse.Namespace) -> object:
    del arguments
    raise CliError(
        "model_backend_unavailable",
        "No model backend is configured. Use a versioned backend that emits "
        "GenerationResultV1; free-text filter fallback is disabled.",
    )


def _parse_observation(
    observation: object, probe_id: str
) -> tuple[tuple[int, ...], float]:
    """Validates an execution observation at the untyped JSON boundary."""
    if not isinstance(observation, dict):
        raise CliError(
            "schema_invalid", f"Missing observation for probe {probe_id}"
        )
    typed_observation = cast(dict[str, object], observation)
    frame_values = typed_observation.get("candidate_frames")
    runtime_value = typed_observation.get("runtime_ms")
    if not isinstance(frame_values, list):
        raise CliError(
            "schema_invalid", f"Invalid observation for probe {probe_id}"
        )
    frame_objects = cast(list[object], frame_values)
    valid_frames = all(
        isinstance(frame, int) and not isinstance(frame, bool)
        for frame in frame_objects
    )
    if (
        not valid_frames
        or not isinstance(runtime_value, (int, float))
        or isinstance(runtime_value, bool)
    ):
        raise CliError(
            "schema_invalid", f"Invalid observation for probe {probe_id}"
        )
    return tuple(cast(list[int], frame_values)), float(runtime_value)


def _evaluate(arguments: argparse.Namespace) -> None:
    spec = _load_model(arguments.spec, SemanticSpecV1)
    candidate_ir = _load_model(arguments.candidate_ir, IntentIrV1)
    observations = _read_json(arguments.observations)
    environment = _load_model(arguments.environment, EnvironmentManifestV1)
    if not isinstance(observations, dict):
        raise CliError("schema_invalid", "observations must be a JSON object")
    observation_map = cast(dict[str, object], observations)
    candidate_filter = compile_intent(candidate_ir)
    probes: list[ProbeResultV1] = []
    for expected in spec.probes:
        observation = observation_map.get(expected.probe_id)
        candidate_frames, runtime_ms = _parse_observation(
            observation, expected.probe_id
        )
        probes.append(
            evaluate_probe(
                expected.probe_id,
                expected.expected_frames,
                candidate_frames,
                runtime_ms,
            )
        )
    typed_probes = tuple(probes)
    receipt = EvaluationReceiptV1(
        run_id=arguments.run_id,
        created_at=arguments.created_at,
        code_revision=arguments.code_revision,
        environment_hash=environment.environment_hash(),
        data_hash=content_sha256(spec),
        model_hash=arguments.model_hash,
        prompt_hash=arguments.prompt_hash,
        candidate_filter=candidate_filter,
        reference_filter=spec.reference_filter,
        probes=typed_probes,
        metrics=aggregate_metrics(typed_probes),
    )
    _write_json(receipt, arguments.output)


def _benchmark_run(arguments: argparse.Namespace) -> object:
    receipts: list[EvaluationReceiptV1] = []
    for path in arguments.receipts:
        receipt = _load_model(path, EvaluationReceiptV1)
        receipts.append(receipt)
    return {
        "receipt_count": len(receipts),
        "receipts": [
            {
                "receipt_hash": receipt.receipt_hash(),
                "run_id": receipt.run_id,
                "metrics": receipt.metrics,
            }
            for receipt in receipts
        ],
    }


def _replay(arguments: argparse.Namespace) -> object:
    receipt = _load_model(arguments.receipt, EvaluationReceiptV1)
    if (
        arguments.environment_hash is not None
        and arguments.environment_hash != receipt.environment_hash
    ):
        raise CliError(
            "environment_mismatch",
            "Current environment hash does not match the receipt",
        )
    return {
        "receipt_hash": receipt.receipt_hash(),
        "run_id": receipt.run_id,
        "validated": True,
    }


def _ablation_run(arguments: argparse.Namespace) -> object:
    receipt = _load_model(arguments.manifest, AblationReceiptV1)
    return {
        "ablation_hash": content_sha256(receipt),
        "ablation_id": receipt.ablation_id,
        "decision": receipt.decision,
    }


def _path(value: str) -> Path:
    return Path(value)


# pylint: disable-next=too-many-locals,too-many-statements
def build_parser() -> argparse.ArgumentParser:
    """Builds the CLI parser without mutating global process state."""
    parser = argparse.ArgumentParser(prog="dfilterforge")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor")
    doctor.add_argument("--tshark", default="tshark")
    doctor.add_argument("--require-tshark-version", default="4.6.8")
    doctor.set_defaults(handler=_doctor)

    catalog = commands.add_parser("catalog")
    catalog_commands = catalog.add_subparsers(
        dest="catalog_command", required=True
    )
    catalog_build = catalog_commands.add_parser("build")
    catalog_build.add_argument("--fields-tsv", type=_path, required=True)
    catalog_build.add_argument("--values-tsv", type=_path)
    catalog_build.add_argument("--tshark-version", required=True)
    catalog_build.add_argument("--profile-hash", required=True)
    catalog_build.add_argument("--output", type=_path)
    catalog_build.set_defaults(handler=_catalog_build)

    spec = commands.add_parser("spec")
    spec_commands = spec.add_subparsers(dest="spec_command", required=True)
    spec_validate = spec_commands.add_parser("validate")
    spec_validate.add_argument("--spec", type=_path, required=True)
    spec_validate.set_defaults(handler=_spec_validate)

    compile_command = commands.add_parser("compile")
    compile_command.add_argument("--intent-ir", type=_path, required=True)
    compile_command.add_argument("--catalog", type=_path)
    compile_command.set_defaults(handler=_compile)

    generate = commands.add_parser("generate")
    generate.add_argument("--intent", required=True)
    generate.add_argument(
        "--pipeline", choices=("prompt", "rag-ir"), required=True
    )
    generate.set_defaults(handler=_generate)

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--spec", type=_path, required=True)
    evaluate.add_argument("--candidate-ir", type=_path, required=True)
    evaluate.add_argument("--observations", type=_path, required=True)
    evaluate.add_argument("--environment", type=_path, required=True)
    evaluate.add_argument("--run-id", required=True)
    evaluate.add_argument("--created-at", required=True)
    evaluate.add_argument("--code-revision", required=True)
    evaluate.add_argument("--model-hash")
    evaluate.add_argument("--prompt-hash")
    evaluate.add_argument("--output", type=_path)
    evaluate.set_defaults(handler=_evaluate)

    benchmark = commands.add_parser("benchmark")
    benchmark_commands = benchmark.add_subparsers(
        dest="benchmark_command", required=True
    )
    benchmark_run = benchmark_commands.add_parser("run")
    benchmark_run.add_argument("--suite")
    benchmark_run.add_argument(
        "--receipts", nargs="+", type=_path, required=True
    )
    benchmark_run.set_defaults(handler=_benchmark_run)

    replay = commands.add_parser("replay-run")
    replay.add_argument("--receipt", type=_path, required=True)
    replay.add_argument("--environment-hash")
    replay.set_defaults(handler=_replay)

    ablation = commands.add_parser("ablation")
    ablation_commands = ablation.add_subparsers(
        dest="ablation_command", required=True
    )
    ablation_run = ablation_commands.add_parser("run")
    ablation_run.add_argument("--manifest", type=_path, required=True)
    ablation_run.set_defaults(handler=_ablation_run)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the CLI and returns a process exit code."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    handler: Command = arguments.handler
    try:
        result = handler(arguments)
        if result is not None:
            _write_json(result, None)
        return 0
    except (CatalogError, CompileError) as error:
        print(
            canonical_json(
                {"error": {"code": error.code, "message": str(error)}}
            ),
            file=sys.stderr,
        )
        return 2
    except CliError as error:
        print(
            canonical_json(
                {"error": {"code": error.code, "message": str(error)}}
            ),
            file=sys.stderr,
        )
        return 2
    except ValidationError as error:
        print(
            canonical_json(
                {"error": {"code": "schema_invalid", "message": str(error)}}
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
