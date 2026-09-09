"""Independent recipe labels, capture diversity, and live semantic witnesses."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
from typing import cast, Protocol

import pytest

from dfilterforge.benchmark import capture_bytes
from dfilterforge.benchmark import generate_benchmark
from dfilterforge.benchmark import RECIPES
from dfilterforge.benchmark import semantic_cases
from dfilterforge.benchmark import SemanticCase
from dfilterforge.canonical import content_sha256
from dfilterforge.catalog_runtime import bind_catalog
from dfilterforge.catalog_runtime import DEFAULT_CATALOG_PATH
from dfilterforge.compiler import compile_intent
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.field_catalog import FieldCatalogV1
from dfilterforge.runner import RunResult
from dfilterforge.runner import TsharkRunner


class _BenchmarkGate(Protocol):
    """Typed view of the standalone benchmark measurement script."""

    def run_stability(
        self,
        output_dir: Path,
        output: Path,
        catalog: FieldCatalogV1,
        source_revision: str,
        *,
        restart: bool = False,
        runner: TsharkRunner | None = None,
    ) -> bool:
        ...


def _load_benchmark_gate() -> _BenchmarkGate:
    path = Path(__file__).parents[1] / "scripts" / "benchmark_gate.py"
    spec = importlib.util.spec_from_file_location("benchmark_gate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("benchmark gate script cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(_BenchmarkGate, module)


benchmark_gate = _load_benchmark_gate()


class _RecordingRunner(TsharkRunner):
    """Fast deterministic runner used to exercise stability checkpointing."""

    def __init__(self, fail_after: int | None = None) -> None:
        super().__init__("unused")
        self.calls = 0
        self.capture_names: list[str] = []
        self._fail_after = fail_after

    def version(self) -> str:
        return "4.6.8"

    def run(self, capture: Path, display_filter: str) -> RunResult:
        self.capture_names.append(capture.name)
        if self._fail_after is not None and self.calls >= self._fail_after:
            raise RuntimeError("simulated interruption")
        self.calls += 1
        capture_bytes_value = capture.read_bytes()
        digest = hashlib.sha256(
            capture_bytes_value + display_filter.encode("utf-8")
        ).digest()
        frames = tuple(
            index + 1 for index in range(4) if digest[0] & (1 << index)
        )
        return RunResult(
            frames=frames,
            runtime_ms=1.0,
            capture_sha256=hashlib.sha256(capture_bytes_value).hexdigest(),
        )


def _catalog() -> FieldCatalogV1:
    return FieldCatalogV1(
        tshark_version="4.6.8",
        profile_hash="profile",
        source_catalog_hash="catalog",
        fields=(),
    )


def test_benchmark_is_reproducible_and_has_real_capture_diversity(
    tmp_path: Path,
) -> None:
    first = generate_benchmark(tmp_path / "first")
    second = generate_benchmark(tmp_path / "second")
    assert len(first) == len(second) == 50
    assert len({probe.capture_path.read_bytes() for probe in first}) == 50
    assert len({probe.recipes for probe in first}) > 25
    assert [probe.capture_path.read_bytes() for probe in first] == [
        probe.capture_path.read_bytes() for probe in second
    ]
    assert (tmp_path / "first/manifest.json").read_bytes() == (
        tmp_path / "second/manifest.json"
    ).read_bytes()
    manifest = json.loads((tmp_path / "first/manifest.json").read_bytes())
    cases = semantic_cases()
    assert len(cases) == len({case.task_id for case in cases}) == 36
    assert len(manifest["specs"]) == 36
    assert manifest["split"] == "pilot"
    assert manifest["status"] == "ready"
    assert manifest["review_status"] == "reviewed"
    raw_specs = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((tmp_path / "first/specs").glob("*.json"))
    ]
    assert len(raw_specs) == 36
    assert all(spec["status"] == "ready" for spec in raw_specs)
    assert all(spec["review_status"] == "reviewed" for spec in raw_specs)
    assert all(spec["schema_version"] == "1.0" for spec in raw_specs)
    assert all(SemanticSpecV1.model_validate(spec) for spec in raw_specs)
    for case in cases:
        assert case.matching_recipes
        assert case.matching_recipes < set(RECIPES)
        assert all(probe.labels(case) for probe in first[1:3])
    assert all(len(spec["probes"]) == 3 for spec in manifest["specs"])


def test_stability_checkpoint_binds_inputs_rejects_stale_and_resumes(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "captures"
    output = tmp_path / "stability.json"
    interrupted = _RecordingRunner(fail_after=300)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        benchmark_gate.run_stability(
            output_dir,
            output,
            _catalog(),
            "705ed13+working-tree",
            runner=interrupted,
        )
    saved = json.loads(output.read_text(encoding="utf-8"))
    identity = saved["measurement_identity"]
    assert interrupted.calls == 300
    assert saved["schema_version"] == "stability-report/2.0"
    assert saved["completed_pairs"] == 150
    assert saved["completed_tshark_calls"] == 300
    assert len(saved["captures"]) == 1
    assert len(saved["filters"]) == 150
    assert len(identity["capture_manifest"]) == 50
    assert identity["source_revision"] == "705ed13+working-tree"
    assert (
        identity["benchmark_source_sha256"]
        == identity["source_files"]["src/dfilterforge/benchmark.py"]
    )
    assert identity["filters_sha256"] == content_sha256(saved["filters"])

    mutations = (
        ("source_revision", "other-revision"),
        ("benchmark_source_sha256", "0" * 64),
        ("capture_manifest_sha256", "1" * 64),
        ("filters_sha256", "2" * 64),
        ("execution_sha256", "3" * 64),
    )
    for name, value in mutations:
        stale = deepcopy(saved)
        stale_identity = stale["measurement_identity"]
        stale_identity[name] = value
        stale["measurement_identity_sha256"] = content_sha256(stale_identity)
        output.write_text(json.dumps(stale), encoding="utf-8")
        unused = _RecordingRunner()
        with pytest.raises(ValueError, match="--restart-stability"):
            benchmark_gate.run_stability(
                output_dir,
                output,
                _catalog(),
                "705ed13+working-tree",
                runner=unused,
            )
        assert unused.calls == 0

    corrupt = deepcopy(saved)
    corrupt["captures"][0]["second_frames"][0] = [999]
    output.write_text(json.dumps(corrupt), encoding="utf-8")
    with pytest.raises(ValueError, match="--restart-stability"):
        benchmark_gate.run_stability(
            output_dir,
            output,
            _catalog(),
            "705ed13+working-tree",
            runner=_RecordingRunner(),
        )

    output.write_text(json.dumps(saved), encoding="utf-8")
    resumed = _RecordingRunner(fail_after=0)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        benchmark_gate.run_stability(
            output_dir,
            output,
            _catalog(),
            "705ed13+working-tree",
            runner=resumed,
        )
    assert resumed.capture_names == ["semantic-02.pcap"]


@pytest.mark.parametrize(
    ("recipes", "seed"),
    (
        ((), 1),
        (("unknown",), 1),
        (("syn",), 0),
        (("syn",), 10001),
        (("syn",) * 201, 1),
    ),
)
def test_capture_generator_rejects_invalid_plans(
    recipes: tuple[str, ...],
    seed: int,
) -> None:
    with pytest.raises(ValueError):
        capture_bytes(recipes, seed)


def test_modified_packets_preserve_ip_and_transport_checksums() -> None:
    capture = capture_bytes(RECIPES, 123)
    offset = 24
    for _ in RECIPES:
        _, _, length, original = struct.unpack(
            "<IIII", capture[offset : offset + 16]
        )
        assert length == original
        packet = capture[offset + 16 : offset + 16 + length]
        ip_end = 14 + int.from_bytes(packet[16:18], "big")
        segment = packet[34:ip_end]
        pseudo = packet[26:34] + struct.pack(
            "!BBH", 0, packet[23], len(segment)
        )
        for data in (packet[14:34], pseudo + segment):
            padded = data + (b"\0" if len(data) % 2 else b"")
            checksum = sum(struct.unpack(f"!{len(padded) // 2}H", padded))
            while checksum >> 16:
                checksum = (checksum & 0xFFFF) + (checksum >> 16)
            assert checksum == 0xFFFF
        offset += length + 16
    assert offset == len(capture)


@pytest.mark.parametrize(
    "case", semantic_cases(), ids=lambda case: case.task_id
)
def test_real_catalog_compilation_and_mutation_witness(
    tmp_path: Path,
    case: SemanticCase,
) -> None:
    probe = generate_benchmark(tmp_path)[1]
    runner = TsharkRunner()
    catalog = bind_catalog(
        runner, (case.canonical_ir,), path=DEFAULT_CATALOG_PATH
    )
    expected = probe.labels(case)
    assert (
        runner.run(
            probe.capture_path, compile_intent(case.canonical_ir, catalog)
        ).frames
        == expected
    )
    assert (
        runner.run(probe.capture_path, case.reference_filter).frames == expected
    )
    assert (
        runner.run(probe.capture_path, case.mutation_filter).frames != expected
    )


def test_single_probe_misses_a_real_syn_ack_mutation(tmp_path: Path) -> None:
    probes = generate_benchmark(tmp_path)
    case = next(
        case for case in semantic_cases() if case.task_id == "syn-no-ack"
    )
    runner = TsharkRunner()
    assert runner.run(
        probes[0].capture_path, case.mutation_filter
    ).frames == probes[0].labels(case)
    assert runner.run(
        probes[1].capture_path, case.mutation_filter
    ).frames != probes[1].labels(case)
