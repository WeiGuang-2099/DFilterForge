"""Non-ready evaluator cases of the model split and their gold records.

Each case holds two independently worded requests. Their gold is a status
and, for needs_clarification, the slots the request leaves open; no filter
answers them. The table lives apart from :mod:`dfilterforge.model_split`,
which turns every case into model inputs and evaluator gold, so the case
list can grow without the contracts module growing with it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from pydantic import Field
from pydantic import model_validator

from dfilterforge.intent_ir import FrozenModel
from dfilterforge.intent_ir import GenerationStatus
from dfilterforge.intent_ir import MissingSlot

CaseSplit: TypeAlias = Literal["dev", "test"]
NonReadyStatus: TypeAlias = Literal["needs_clarification", "not_expressible"]


class ModelNonReadyCaseV1(FrozenModel):
    """Evaluator-only gold for a request no single filter should answer.

    A needs_clarification case names the slots its request leaves open, one
    or more from the closed list; a not_expressible case names none.
    """

    case_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    split: CaseSplit
    status: NonReadyStatus
    missing_slots: tuple[MissingSlot, ...] = ()
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_slots(self) -> "ModelNonReadyCaseV1":
        """Keeps the gold slots consistent with the gold status."""
        if len(set(self.missing_slots)) != len(self.missing_slots):
            raise ValueError("gold missing_slots must be unique")
        needs_slots = self.status == GenerationStatus.NEEDS_CLARIFICATION
        if needs_slots != bool(self.missing_slots):
            raise ValueError(
                "needs_clarification gold needs slots; not_expressible none"
            )
        return self


@dataclass(frozen=True)
class ModelNonReadyCase:
    """One non-ready evaluator case with two independently worded requests.

    Attributes:
        case_id: Stable evaluator identifier, never shown to a model.
        split: The split the case belongs to.
        status: The status the gold expects.
        paraphrases: The two model-visible requests.
        missing_slots: The slots a needs_clarification request leaves open;
            empty for not_expressible.
        rationale: Why no single-packet filter answers the request.
    """

    case_id: str
    split: CaseSplit
    status: NonReadyStatus
    paraphrases: tuple[str, str]
    missing_slots: tuple[MissingSlot, ...]
    rationale: str

    def gold(self) -> ModelNonReadyCaseV1:
        """Returns the evaluator-only gold record of this case."""
        return ModelNonReadyCaseV1(
            case_id=self.case_id,
            split=self.split,
            status=self.status,
            missing_slots=self.missing_slots,
            rationale=self.rationale,
        )


def model_non_ready_cases() -> tuple[ModelNonReadyCase, ...]:
    """Returns the needs_clarification and not_expressible compositions."""
    return ()
