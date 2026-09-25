"""Unscored feedback probes of the model split.

A repair round may show a model packets its filter got wrong. Those packets
must never come from a probe that scores it, so each split gets one more
capture that no score, gold hash or model input reads: an unused benchmark
capture with the witness tail of :mod:`dfilterforge.witnesses`, copied the
way :mod:`dfilterforge.model_split` copies the scored probes, on a seed no
other probe uses. Every ready case of the split is labelled on it from the
same recipe and witness memberships as on its scored probes.

No module that builds prompts, calls a model or scores may import this one;
the import contracts in ``pyproject.toml`` enforce it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path
from types import MappingProxyType

from dfilterforge.benchmark import BenchmarkProbe
from dfilterforge.canonical import content_sha256
from dfilterforge.evaluation import ProbeExpectationV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.model_split import copy_with_witnesses
from dfilterforge.model_split import model_semantic_cases
from dfilterforge.model_split import ModelSplit
from dfilterforge.model_split import ModelSplitArtifacts

# One capture per split, shared by its ready cases like the scored probes.
# Seeds 128 and 134 (100 + benchmark index) belong to no scored, suite or
# pilot probe. Their clients, 192.0.2.129 and .135, lie outside
# 192.0.2.0/25, which the /25 subnet mutant of a TEST-NET-1 case needs.
FEEDBACK_PROBE_IDS: Mapping[ModelSplit, str] = MappingProxyType(
    {"dev": "semantic-29", "test": "semantic-35"}
)
_PROVENANCE = (
    "Feedback view of a model split case for the repair round: its gold "
    "specification with its split's unscored feedback capture as the only "
    "probe, a benchmark copy with the witness tail of dfilterforge.witnesses, "
    "labelled from the same recipe and witness memberships. No score reads it."
)


@dataclass(frozen=True)
class FeedbackProbes:
    """The feedback captures and every ready case's specification on them."""

    capture_dir: Path
    # The dev copy, then the test copy, with their recipe and witness order.
    probes: tuple[BenchmarkProbe, ...]
    # Ready case ID to its gold specification with its split's feedback
    # probe as the only probe, in gold order.
    specs: Mapping[str, SemanticSpecV1]


def generate_feedback_probes(split: ModelSplitArtifacts) -> FeedbackProbes:
    """Writes the feedback captures beside a generated split and labels them.

    The captures go to ``feedback/`` next to the split's ``captures/``, the
    only folder scoring reads. No input, gold or scored capture file changes.

    Args:
        split: A generated model split; each ready gold case is labelled.

    Returns:
        Both feedback captures and one single-probe specification per ready
        case.
    """
    capture_dir = split.gold_path.parent / "feedback"
    copies = copy_with_witnesses(FEEDBACK_PROBE_IDS.values(), capture_dir)
    by_split = {
        name: copies[probe_id] for name, probe_id in FEEDBACK_PROBE_IDS.items()
    }
    oracles = {case.case_id: case for case in model_semantic_cases()}
    specs: dict[str, SemanticSpecV1] = {}
    for gold in split.gold.cases:
        probe = by_split[gold.spec.split]
        expectation = ProbeExpectationV1(
            probe_id=probe.probe_id,
            capture_sha256=hashlib.sha256(
                probe.capture_path.read_bytes()
            ).hexdigest(),
            expected_frames=oracles[gold.case_id].labels(probe),
        )
        # Validated anew, not copied: a copy would skip the spec's checks.
        specs[gold.case_id] = SemanticSpecV1.model_validate(
            {
                **gold.spec.model_dump(),
                "probes": (expectation.model_dump(),),
                "provenance": _PROVENANCE,
            }
        )
    return FeedbackProbes(
        capture_dir,
        (by_split["dev"], by_split["test"]),
        MappingProxyType(specs),
    )


def feedback_labels_sha256(feedback: FeedbackProbes, split: ModelSplit) -> str:
    """Digests one split's feedback expectations, keyed by ready case ID.

    It covers the probe ID, capture hash and expected frames of each case of
    the split and nothing of its gold wording, so the adequacy receipt and
    the test freeze can quote one value for the labels a repair round uses.
    """
    return content_sha256(
        {
            case_id: spec.probes[0]
            for case_id, spec in feedback.specs.items()
            if spec.split == split
        }
    )
