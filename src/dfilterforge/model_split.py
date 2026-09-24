"""Model-safe inputs and evaluator gold of the held-out model split.

The split deliberately reuses the benchmark's packet recipes and protocols.
It holds out predicate compositions and capture instances, not recipe or
protocol families. The compositions themselves are the ready tables of
:mod:`dfilterforge.model_dev_cases` and :mod:`dfilterforge.model_test_cases`
and the non-ready table of :mod:`dfilterforge.model_cases`. Each probe copy
ends in a tail of witness packets that separate near-miss filters the
recipes alone cannot. Evaluator gold is written separately from model
inputs.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, TypeAlias

from pydantic import Field
from pydantic import model_validator

from dfilterforge.benchmark import BenchmarkProbe
from dfilterforge.benchmark import generate_benchmark
from dfilterforge.evaluation import ProbeExpectationV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.model_cases import model_non_ready_cases
from dfilterforge.model_cases import ModelNonReadyCase
from dfilterforge.model_cases import ModelNonReadyCaseV1
from dfilterforge.model_cases import ModelSemanticCase
from dfilterforge.model_dev_cases import ready_dev_cases
from dfilterforge.model_test_cases import ready_test_cases
from dfilterforge.mutants import MutantWaiver
from dfilterforge.witnesses import append_witnesses
from dfilterforge.witnesses import WITNESS_NAMES

ModelSplit = Literal["dev", "test"]

_CAPTURE_IDS: dict[ModelSplit, tuple[str, ...]] = {
    "dev": ("semantic-11", "semantic-17", "semantic-23"),
    "test": ("semantic-31", "semantic-37", "semantic-43"),
}
_USER_ASSUMPTIONS = (
    "Interpret the request at packet scope over complete Ethernet/IPv4 "
    "packets.",
    "Treat source and destination constraints as directional.",
)
_SPEC_ASSUMPTIONS = (
    "Complete synthetic Ethernet/IPv4 TCP and UDP packets only.",
    "mDNS exposes shared dns.* fields but remains a distinct protocol.",
    "Equivalence applies only to the selected probes and pinned environment.",
)
# Evaluator-only readings of one case's wording, added to the shared
# specification assumptions; the model never sees them.
_CASE_ASSUMPTIONS: dict[str, tuple[str, ...]] = {
    "fin-or-dns-response": (
        "All DNS responses include mDNS responses, which carry the same "
        "dns.* response flag.",
    ),
}
# The first item number of each split's ready and non-ready cases. Each
# block is numbered on its own, so a case added to one block renumbers no
# item of another: the dev items published runs answered keep their IDs,
# and no dev change moves a test ID.
_ITEM_BLOCKS: dict[tuple[ModelSplit, bool], int] = {
    ("dev", True): 1,
    ("dev", False): 501,
    ("test", True): 1001,
    ("test", False): 1501,
}
_BLOCK_ITEMS = 500
_PROVENANCE = (
    "Model evaluation cases authored as held-out compositions over the same "
    "packet recipes and protocol families as dfilterforge.benchmark/v1. Dev "
    "uses copies of semantic-11/17/23 and test copies of semantic-31/37/43, "
    "rather than the original semantic-suite probes semantic-01/02/03; each "
    "copy keeps the benchmark frames byte for byte and appends the 33 "
    "witness packets of dfilterforge.witnesses. This is strictly an "
    "unseen-composition plus unseen-capture-instance split; it is not an "
    "unseen-recipe or unseen-protocol split. Labels are authored from recipe "
    "and witness membership rather than inferred from display filters, and "
    "scripts/probe_adequacy.py checks them with tshark on all six probes."
)


class ModelInputItemV1(FrozenModel):
    """The complete model-visible contract for one paraphrased request."""

    item_id: str = Field(pattern=r"^mei-[0-9]{4}$")
    intent: str = Field(min_length=1)
    user_assumptions: tuple[str, ...] = Field(min_length=1)
    split: ModelSplit


class ModelGoldCaseV1(FrozenModel):
    """Evaluator-only canonical target and its authored near-wrong filter."""

    case_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    spec: SemanticSpecV1
    mutation_filter: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case_identity(self) -> "ModelGoldCaseV1":
        """Keeps the evaluator case identity aligned with its specification."""
        if self.spec.task_id != self.case_id:
            raise ValueError("gold case_id must match spec.task_id")
        if self.spec.split not in _CAPTURE_IDS:
            raise ValueError("gold specifications must use dev or test split")
        expected_probe_ids = _CAPTURE_IDS[self.spec.split]
        if tuple(probe.probe_id for probe in self.spec.probes) != (
            expected_probe_ids
        ):
            raise ValueError("gold probes do not match the declared split")
        return self


# The gold one model item routes to.
GoldCase: TypeAlias = ModelGoldCaseV1 | ModelNonReadyCaseV1


class ModelGoldV1(FrozenModel):
    """Evaluator-only targets and opaque model-item routing."""

    schema_version: Literal["model-gold/1.0"] = "model-gold/1.0"
    cases: tuple[ModelGoldCaseV1, ...] = Field(min_length=1)
    non_ready: tuple[ModelNonReadyCaseV1, ...] = ()
    item_to_case: dict[str, str]

    @model_validator(mode="after")
    def validate_item_routing(self) -> "ModelGoldV1":
        """Requires unique cases and exactly two items routed to each case."""
        case_ids = tuple(case.case_id for case in self.cases) + tuple(
            case.case_id for case in self.non_ready
        )
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("gold case IDs must be unique")
        if not self.item_to_case:
            raise ValueError("gold item routing cannot be empty")
        if any(not item_id.startswith("mei-") for item_id in self.item_to_case):
            raise ValueError("gold routing requires opaque model item IDs")
        unknown = set(self.item_to_case.values()) - set(case_ids)
        if unknown:
            raise ValueError("gold routing references an unknown case")
        counts = Counter(self.item_to_case.values())
        if any(counts[case_id] != 2 for case_id in case_ids):
            raise ValueError("every gold case requires exactly two model items")
        return self


@dataclass(frozen=True)
class ModelSplitArtifacts:
    """In-memory contracts and paths emitted by split generation."""

    inputs: tuple[ModelInputItemV1, ...]
    gold: ModelGoldV1
    inputs_path: Path
    gold_path: Path
    capture_paths: tuple[Path, ...]
    # The same captures with their recipe and witness order, for labels on
    # any probe.
    probes: tuple[BenchmarkProbe, ...]


def model_semantic_cases() -> tuple[ModelSemanticCase, ...]:
    """Returns the ready dev compositions, then the ready test ones."""
    return (*ready_dev_cases(), *ready_test_cases())


# Single-site mutants of the ready cases that the probes may leave alive,
# each with a reason. scripts/probe_adequacy.py fails on any other survivor
# and on any waiver that no longer matches a survivor.
MUTANT_WAIVERS: tuple[MutantWaiver, ...] = (
    MutantWaiver(
        case_id="private-either-endpoint",
        edit="0: ip.src -> ip.addr",
        display_filter="(ip.addr == 10.0.0.0/8 || ip.dst == 10.0.0.0/8)",
        kind="equivalent",
        reason=(
            "ip.addr matches exactly where ip.src or ip.dst does, and the "
            "other branch already tests ip.dst."
        ),
    ),
    MutantWaiver(
        case_id="private-either-endpoint",
        edit="1: ip.dst -> ip.addr",
        display_filter="(ip.src == 10.0.0.0/8 || ip.addr == 10.0.0.0/8)",
        kind="equivalent",
        reason=(
            "ip.addr matches exactly where ip.src or ip.dst does, and the "
            "other branch already tests ip.src."
        ),
    ),
    MutantWaiver(
        case_id="dns-destination-not-source",
        edit="0: udp.dstport -> udp.port",
        display_filter="(udp.port == 53 && udp.srcport != 53)",
        kind="equivalent",
        reason=(
            "With the source port required not to be 53, udp.port == 53 can "
            "only match the destination port."
        ),
    ),
    MutantWaiver(
        case_id="successful-source-dns",
        edit="0: udp.srcport -> udp.port",
        display_filter=(
            "(udp.port == 53 && udp.dstport != 53 && dns.flags.rcode == 0)"
        ),
        kind="equivalent",
        reason=(
            "With the destination port required not to be 53, udp.port == 53 "
            "can only match the source port."
        ),
    ),
)


def _copy_selected_probes(output_dir: Path) -> tuple[BenchmarkProbe, ...]:
    """Copies the six selected benchmark captures and appends witnesses."""
    capture_dir = output_dir / "captures"
    capture_dir.mkdir(parents=True, exist_ok=True)
    selected_ids = {
        probe_id
        for probe_ids in _CAPTURE_IDS.values()
        for probe_id in probe_ids
    }
    selected: list[BenchmarkProbe] = []
    with TemporaryDirectory(prefix="dfilterforge-model-split-") as staging:
        generated = generate_benchmark(Path(staging))
        # generate_benchmark builds capture i with seed 100 + i.
        for seed, probe in enumerate(generated, 100):
            if probe.probe_id not in selected_ids:
                continue
            target = capture_dir / probe.capture_path.name
            target.write_bytes(
                append_witnesses(
                    probe.capture_path.read_bytes(), seed, len(probe.recipes)
                )
            )
            selected.append(
                BenchmarkProbe(
                    probe.probe_id, target, probe.recipes + WITNESS_NAMES
                )
            )
    order = {
        probe_id: index
        for index, probe_id in enumerate(
            probe_id
            for split in ("dev", "test")
            for probe_id in _CAPTURE_IDS[split]
        )
    }
    return tuple(sorted(selected, key=lambda probe: order[probe.probe_id]))


def _build_gold_case(
    case: ModelSemanticCase, probes: dict[str, BenchmarkProbe]
) -> ModelGoldCaseV1:
    expectations: list[ProbeExpectationV1] = []
    for probe_id in _CAPTURE_IDS[case.split]:
        probe = probes[probe_id]
        capture = probe.capture_path.read_bytes()
        expectations.append(
            ProbeExpectationV1(
                probe_id=probe_id,
                capture_sha256=hashlib.sha256(capture).hexdigest(),
                expected_frames=case.labels(probe),
            )
        )
    spec = SemanticSpecV1(
        task_id=case.case_id,
        intent=case.paraphrases[0],
        assumptions=_SPEC_ASSUMPTIONS + _CASE_ASSUMPTIONS.get(case.case_id, ()),
        canonical_ir=case.canonical_ir,
        reference_filter=case.reference_filter,
        probes=tuple(expectations),
        split=case.split,
        provenance=_PROVENANCE,
        license="MIT",
        review_status="reviewed",
    )
    return ModelGoldCaseV1(
        case_id=case.case_id,
        spec=spec,
        mutation_filter=case.mutation_filter,
    )


def _numbered_items(
    cases: Sequence[ModelSemanticCase],
    non_ready: Sequence[ModelNonReadyCase],
) -> tuple[list[ModelInputItemV1], dict[str, str]]:
    """Numbers every request in its block and routes it to its case.

    Args:
        cases: The ready cases, dev first.
        non_ready: The non-ready cases.

    Returns:
        The model items in block order and the item-to-case routing.

    Raises:
        ValueError: If a block holds more items than it has numbers.
    """
    inputs: list[ModelInputItemV1] = []
    routes: dict[str, str] = {}
    for (split, ready), first in _ITEM_BLOCKS.items():
        block = [
            case
            for case in (cases if ready else non_ready)
            if case.split == split
        ]
        if 2 * len(block) > _BLOCK_ITEMS:
            raise ValueError(
                f"the {split} item block for ready={ready} is full"
            )
        for number, (case, intent) in enumerate(
            ((case, intent) for case in block for intent in case.paraphrases),
            first,
        ):
            item_id = f"mei-{number:04d}"
            inputs.append(
                ModelInputItemV1(
                    item_id=item_id,
                    intent=intent,
                    user_assumptions=_USER_ASSUMPTIONS,
                    split=case.split,
                )
            )
            routes[item_id] = case.case_id
    return inputs, routes


def generate_model_split(output_dir: Path) -> ModelSplitArtifacts:
    """Writes model-safe inputs, evaluator-only gold, and six captures.

    Existing generated files with the same names are replaced. No descriptive
    case identity, typed IR, filter, probe, frame, or capture metadata enters
    ``model_inputs.jsonl``. Items are numbered in the blocks of
    ``_ITEM_BLOCKS``: dev ready, dev non-ready, test ready, test non-ready.

    Args:
        output_dir: Destination for the two contracts and selected captures.

    Returns:
        The validated in-memory contracts and their generated filesystem paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    capture_probes = _copy_selected_probes(output_dir)
    probes_by_id = {probe.probe_id: probe for probe in capture_probes}
    cases = model_semantic_cases()
    non_ready = model_non_ready_cases()
    inputs, routes = _numbered_items(cases, non_ready)
    gold = ModelGoldV1(
        cases=tuple(_build_gold_case(case, probes_by_id) for case in cases),
        non_ready=tuple(case.gold() for case in non_ready),
        item_to_case=routes,
    )
    inputs_path = output_dir / "model_inputs.jsonl"
    encoded_inputs = "".join(
        json.dumps(item.model_dump(mode="json"), sort_keys=True) + "\n"
        for item in inputs
    )
    inputs_path.write_text(encoded_inputs, encoding="utf-8")
    gold_path = output_dir / "evaluator_gold.json"
    gold_path.write_text(
        gold.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return ModelSplitArtifacts(
        inputs=tuple(inputs),
        gold=gold,
        inputs_path=inputs_path,
        gold_path=gold_path,
        capture_paths=tuple(probe.capture_path for probe in capture_probes),
        probes=capture_probes,
    )
