"""Command-line interface for deterministic core workflows."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import datetime
import json
from pathlib import Path
import platform
import sys
from typing import cast, TypeVar

from pydantic import BaseModel
from pydantic import ValidationError

from dfilterforge import __version__
from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import content_sha256
from dfilterforge.catalog_runtime import bind_catalog
from dfilterforge.catalog_runtime import freeze_catalog
from dfilterforge.compiler import compile_intent
from dfilterforge.errors import DFilterForgeError
from dfilterforge.evaluation import AblationReceiptV1
from dfilterforge.evaluation import aggregate_metrics
from dfilterforge.evaluation import EnvironmentManifestV1
from dfilterforge.evaluation import evaluate_probe
from dfilterforge.evaluation import EvaluationReceiptV1
from dfilterforge.evaluation import ProbeResultV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.field_catalog import apply_enum_values
from dfilterforge.field_catalog import FieldCatalogV1
from dfilterforge.field_catalog import parse_tshark_fields
from dfilterforge.field_catalog import parse_tshark_values
from dfilterforge.fixtures import generate_fixtures
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.live import evaluate_live_with_trace
from dfilterforge.live import packet_set_hash
from dfilterforge.pair_report import pair_runs
from dfilterforge.repair import repair_run
from dfilterforge.replay import replay_live
from dfilterforge.runner import RunnerError
from dfilterforge.runner import TsharkRunner
from dfilterforge.scoring import score_run

JsonObject = dict[str, object]
Command = Callable[[argparse.Namespace], object]
ModelT = TypeVar("ModelT", bound=BaseModel)


class CliError(DFilterForgeError, RuntimeError):
    """A user-facing error with a stable machine-readable code."""


def _read_json(path: Path) -> object:
    try:
        with path.open("r", encoding="utf-8") as source:
            return json.load(source)
    except (OSError, UnicodeError, ValueError):
        raise CliError(
            "input_invalid", "Cannot read valid JSON input"
        ) from None


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
    except ValidationError:
        raise CliError(
            "schema_invalid", "Input does not match the required schema"
        ) from None


def _optional_catalog(arguments: argparse.Namespace) -> FieldCatalogV1 | None:
    """Loads the caller-supplied catalog projection when one was given."""
    if arguments.catalog is None:
        return None
    return _load_model(arguments.catalog, FieldCatalogV1)


def _print_error(code: str, message: str) -> None:
    """Writes the machine-readable error envelope to stderr."""
    print(
        canonical_json({"error": {"code": code, "message": message}}),
        file=sys.stderr,
    )


def _doctor(arguments: argparse.Namespace) -> object:
    tshark_status: JsonObject
    try:
        version = TsharkRunner(tshark=arguments.tshark).version()
        version_ok = version == arguments.require_tshark_version
        tshark_status = {
            "available": True,
            "required_version": arguments.require_tshark_version,
            "version": version,
            "version_ok": version_ok,
        }
        if not version_ok:
            arguments.exit_code = 2
    except RunnerError as error:
        arguments.exit_code = 2
        tshark_status = {
            "available": False,
            "error": error.code,
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
    catalog = bind_catalog(
        TsharkRunner(tshark=arguments.tshark),
        (intent,),
        _optional_catalog(arguments),
    )
    return {
        "display_filter": compile_intent(intent, catalog),
        "intent_hash": content_sha256(intent),
    }


def _catalog_freeze(arguments: argparse.Namespace) -> object:
    metadata = freeze_catalog(
        arguments.output, TsharkRunner(tshark=arguments.tshark)
    )
    return {
        "catalog_path": arguments.output.as_posix(),
        "counts": metadata["counts"],
        "catalog_hash": metadata["catalog_hash"],
    }


def _spec_validate(arguments: argparse.Namespace) -> object:
    """Checks a specification against its schema and prints its content hash.

    Nothing is executed: captures are neither read nor hashed here.
    """
    spec = _load_model(arguments.spec, SemanticSpecV1)
    return {
        "schema_version": spec.schema_version,
        "spec_hash": content_sha256(spec),
    }


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
    # Bind exactly as the live path does so replay recompiles to this text.
    catalog = bind_catalog(
        TsharkRunner(tshark=arguments.tshark),
        (candidate_ir, spec.canonical_ir),
        _optional_catalog(arguments),
    )
    candidate_filter = compile_intent(candidate_ir, catalog)
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


def _fixtures_generate(arguments: argparse.Namespace) -> object:
    manifest = generate_fixtures(arguments.output_dir)
    return {"manifest_path": manifest.as_posix()}


def _evaluate_live(arguments: argparse.Namespace) -> object:
    spec = _load_model(arguments.spec, SemanticSpecV1)
    candidate_ir = _load_model(arguments.candidate_ir, IntentIrV1)
    receipt, environment, trace = evaluate_live_with_trace(
        spec,
        candidate_ir,
        arguments.capture_root,
        run_id=arguments.run_id,
        created_at=arguments.created_at,
        code_revision=arguments.code_revision,
        catalog=_optional_catalog(arguments),
        runner=TsharkRunner(tshark=arguments.tshark),
    )
    summary: JsonObject = {
        "receipt_hash": receipt.receipt_hash(),
        "environment_hash": environment.environment_hash(),
        "packet_set_hash": packet_set_hash(receipt),
    }
    if arguments.output is None:
        return {
            **summary,
            "receipt": receipt,
            "environment": environment,
            "trace": trace,
        }
    output = cast(Path, arguments.output)
    environment_output = output.with_name(f"{output.stem}.environment.json")
    trace_output = output.with_name(f"{output.stem}.trace.json")
    _write_json(receipt, output)
    _write_json(environment, environment_output)
    _write_json(trace, trace_output)
    return {
        **summary,
        "receipt_path": output.as_posix(),
        "environment_path": environment_output.as_posix(),
        "trace_path": trace_output.as_posix(),
    }


def _benchmark_run(arguments: argparse.Namespace) -> object:
    """Summarizes recorded receipts; it does not execute any capture."""
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
    spec = _load_model(arguments.spec, SemanticSpecV1)
    candidate: IntentIrV1 | str = (
        receipt.candidate_filter
        if arguments.receipt_filter
        else _load_model(arguments.candidate_ir, IntentIrV1)
    )
    replay, environment = replay_live(
        receipt,
        spec,
        candidate,
        arguments.capture_root,
        catalog=_optional_catalog(arguments),
        runner=TsharkRunner(tshark=arguments.tshark),
    )
    arguments.exit_code = 0 if replay.exact else 1
    result = {"replay": replay, "environment": environment}
    if arguments.output is None:
        return result
    _write_json(result, arguments.output)
    return {
        "run_id": replay.run_id,
        "exact": replay.exact,
        "output_path": arguments.output.as_posix(),
    }


def _score(arguments: argparse.Namespace) -> object:
    """Scores stored completions offline and reports the scored directory."""
    report = score_run(
        arguments.run_dir,
        code_revision=arguments.code_revision,
        check=arguments.check,
        control=arguments.control,
        split_dir=arguments.split_dir,
        runner=TsharkRunner(tshark=arguments.tshark),
    )
    if report.differences:
        arguments.exit_code = 1
    return report


def _repair(arguments: argparse.Namespace) -> object:
    """Writes or checks a scored pass's repair plan offline."""
    report = repair_run(
        arguments.run_dir,
        code_revision=arguments.code_revision,
        check=arguments.check,
        runner=TsharkRunner(tshark=arguments.tshark),
    )
    if report.differences:
        arguments.exit_code = 1
    return report


def _pair(arguments: argparse.Namespace) -> object:
    """Reports what changed between two scored passes over the same items."""
    return pair_runs(arguments.first_run_dir, arguments.second_run_dir)


def _ablation_run(arguments: argparse.Namespace) -> object:
    """Checks a recorded ablation receipt and prints its identity.

    No ablation is executed here. Receipts come from the ablation scripts
    under ``scripts/``; this command only re-validates the schema and reports
    the receipt hash, identifier, and recorded decision.
    """
    receipt = _load_model(arguments.manifest, AblationReceiptV1)
    return {
        "ablation_hash": content_sha256(receipt),
        "ablation_id": receipt.ablation_id,
        "decision": receipt.decision,
    }


def _path(value: str) -> Path:
    return Path(value)


_SPEC_VALIDATE_HELP = (
    "Validate a specification's schema and print its content hash; "
    "nothing is executed."
)
_BENCHMARK_RUN_HELP = (
    "Summarize recorded evaluation receipts; no capture is executed."
)
_RECEIPT_FILTER_HELP = (
    "Replay the receipt's own display filter as a display-filter candidate."
)
_SCORE_HELP = (
    "Score stored completions offline against regenerated gold; --check "
    "re-executes and compares without writing; --control scores "
    "gold-derived reference or mutation answers instead of stored "
    "completions."
)
_REPAIR_HELP = (
    "Write a scored pass's repair plan, its silent-wrong and invalid C4 "
    "items with their feedback-probe cards, to repair/plan.json; --check "
    "derives it again and compares bytes without writing."
)
_PAIR_HELP = (
    "Report two scored passes over the same items: per condition the "
    "changed answers, outcome transitions and flipped cases, and each "
    "condition comparison against the pair's rerun noise; reads committed "
    "files only and executes nothing."
)
_ABLATION_RUN_HELP = (
    "Validate a recorded ablation receipt and print its hash, identifier, "
    "and decision; no ablation is executed."
)


# pylint: disable-next=too-many-locals,too-many-statements
def build_parser() -> argparse.ArgumentParser:
    """Builds the CLI parser without mutating global process state."""
    parser = argparse.ArgumentParser(prog="dfilterforge")
    parser.set_defaults(exit_code=0)
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
    catalog_freeze = catalog_commands.add_parser("freeze")
    catalog_freeze.add_argument("--output", type=_path, required=True)
    catalog_freeze.add_argument("--tshark", default="tshark")
    catalog_freeze.set_defaults(handler=_catalog_freeze)

    spec = commands.add_parser("spec")
    spec_commands = spec.add_subparsers(dest="spec_command", required=True)
    spec_validate = spec_commands.add_parser(
        "validate", help=_SPEC_VALIDATE_HELP, description=_SPEC_VALIDATE_HELP
    )
    spec_validate.add_argument("--spec", type=_path, required=True)
    spec_validate.set_defaults(handler=_spec_validate)

    compile_command = commands.add_parser("compile")
    compile_command.add_argument("--intent-ir", type=_path, required=True)
    compile_command.add_argument("--catalog", type=_path)
    compile_command.add_argument("--tshark", default="tshark")
    compile_command.set_defaults(handler=_compile)

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--spec", type=_path, required=True)
    evaluate.add_argument("--candidate-ir", type=_path, required=True)
    evaluate.add_argument("--observations", type=_path, required=True)
    evaluate.add_argument("--environment", type=_path, required=True)
    evaluate.add_argument("--catalog", type=_path)
    evaluate.add_argument("--tshark", default="tshark")
    evaluate.add_argument("--run-id", required=True)
    evaluate.add_argument("--created-at", required=True)
    evaluate.add_argument("--code-revision", required=True)
    evaluate.add_argument("--model-hash")
    evaluate.add_argument("--prompt-hash")
    evaluate.add_argument("--output", type=_path)
    evaluate.set_defaults(handler=_evaluate)

    fixtures = commands.add_parser("fixtures")
    fixture_commands = fixtures.add_subparsers(
        dest="fixtures_command", required=True
    )
    fixture_generate = fixture_commands.add_parser("generate")
    fixture_generate.add_argument("--output-dir", type=_path, required=True)
    fixture_generate.set_defaults(handler=_fixtures_generate)

    live = commands.add_parser("evaluate-live")
    live.add_argument("--spec", type=_path, required=True)
    live.add_argument("--candidate-ir", type=_path, required=True)
    live.add_argument("--capture-root", type=_path, required=True)
    live.add_argument("--catalog", type=_path)
    live.add_argument("--run-id", required=True)
    live.add_argument(
        "--created-at", type=datetime.fromisoformat, required=True
    )
    live.add_argument("--code-revision", required=True)
    live.add_argument("--output", type=_path)
    live.add_argument("--tshark", default="tshark")
    live.set_defaults(handler=_evaluate_live)

    benchmark = commands.add_parser("benchmark")
    benchmark_commands = benchmark.add_subparsers(
        dest="benchmark_command", required=True
    )
    benchmark_run = benchmark_commands.add_parser(
        "run", help=_BENCHMARK_RUN_HELP, description=_BENCHMARK_RUN_HELP
    )
    benchmark_run.add_argument(
        "--receipts", nargs="+", type=_path, required=True
    )
    benchmark_run.set_defaults(handler=_benchmark_run)

    replay = commands.add_parser("replay-run")
    replay.add_argument("--receipt", type=_path, required=True)
    replay.add_argument("--spec", type=_path, required=True)
    candidate_source = replay.add_mutually_exclusive_group(required=True)
    candidate_source.add_argument("--candidate-ir", type=_path)
    candidate_source.add_argument(
        "--receipt-filter", action="store_true", help=_RECEIPT_FILTER_HELP
    )
    replay.add_argument("--capture-root", type=_path, required=True)
    replay.add_argument("--catalog", type=_path)
    replay.add_argument("--tshark", default="tshark")
    replay.add_argument("--output", type=_path)
    replay.set_defaults(handler=_replay)

    score = commands.add_parser(
        "score", help=_SCORE_HELP, description=_SCORE_HELP
    )
    score.add_argument("--run-dir", type=_path, required=True)
    score.add_argument("--code-revision", required=True)
    score.add_argument("--check", action="store_true")
    score.add_argument("--split-dir", type=_path)
    score.add_argument("--control", choices=("reference", "mutation"))
    score.add_argument("--tshark", default="tshark")
    score.set_defaults(handler=_score)

    repair = commands.add_parser(
        "repair", help=_REPAIR_HELP, description=_REPAIR_HELP
    )
    repair.add_argument("--run-dir", type=_path, required=True)
    repair.add_argument("--code-revision", required=True)
    repair.add_argument("--check", action="store_true")
    repair.add_argument("--tshark", default="tshark")
    repair.set_defaults(handler=_repair)

    pair = commands.add_parser("pair", help=_PAIR_HELP, description=_PAIR_HELP)
    pair.add_argument("--first-run-dir", type=_path, required=True)
    pair.add_argument("--second-run-dir", type=_path, required=True)
    pair.set_defaults(handler=_pair)

    ablation = commands.add_parser("ablation")
    ablation_commands = ablation.add_subparsers(
        dest="ablation_command", required=True
    )
    ablation_run = ablation_commands.add_parser(
        "run", help=_ABLATION_RUN_HELP, description=_ABLATION_RUN_HELP
    )
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
        return int(arguments.exit_code)
    except DFilterForgeError as error:
        _print_error(error.code, str(error))
    except ValidationError:
        _print_error(
            "schema_invalid", "Input does not match the required schema"
        )
    except OSError:
        _print_error("io_error", "File operation failed")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
