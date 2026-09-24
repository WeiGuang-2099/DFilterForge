"""Evaluator cases of the model split and their gold records.

Each case holds two independently worded requests. A ready case pairs them
with a canonical typed target, its reference filter, an authored near-wrong
mutation filter and recipe and witness memberships authored apart from both
filters; its tables live in :mod:`dfilterforge.model_dev_cases` and
:mod:`dfilterforge.model_test_cases`. A non-ready case's gold is a status
and, for needs_clarification, the slots the request leaves open; no filter
answers it, and its table is here. All of them live apart from
:mod:`dfilterforge.model_split`, which turns every case into model inputs
and evaluator gold, so the case lists can grow without the contracts module
growing with them.
"""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Literal, TypeAlias

from pydantic import Field
from pydantic import model_validator

from dfilterforge.benchmark import BenchmarkProbe
from dfilterforge.intent_ir import Expression
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.intent_ir import GenerationStatus
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import MissingSlot
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.intent_ir import ScalarValue

CaseSplit: TypeAlias = Literal["dev", "test"]
NonReadyStatus: TypeAlias = Literal["needs_clarification", "not_expressible"]


@dataclass(frozen=True)
class RecipeOracle:
    """Independent canonical and mutation recipe and witness memberships."""

    canonical: frozenset[str]
    mutation: frozenset[str]


@dataclass(frozen=True)
class ModelSemanticCase:
    """One evaluator case with two independently worded model requests."""

    case_id: str
    split: CaseSplit
    paraphrases: tuple[str, str]
    expression: Expression
    reference_filter: str
    mutation_filter: str
    recipe_oracle: RecipeOracle

    @property
    def canonical_ir(self) -> IntentIrV1:
        """Returns the canonical typed target for this case."""
        return IntentIrV1(expression=self.expression)

    def labels(
        self, probe: BenchmarkProbe, *, mutation: bool = False
    ) -> tuple[int, ...]:
        """Maps the independently authored recipe oracle to frame numbers."""
        memberships = (
            self.recipe_oracle.mutation
            if mutation
            else self.recipe_oracle.canonical
        )
        return tuple(
            index
            for index, recipe in enumerate(probe.recipes, 1)
            if recipe in memberships
        )


def predicate(
    field: str,
    operator: Operator = Operator.EXISTS,
    value: ScalarValue | tuple[ScalarValue, ...] | None = None,
) -> Predicate:
    """Builds one typed predicate; the operator defaults to existence."""
    return Predicate(field=field, operator=operator, value=value)


def oracle(
    canonical: AbstractSet[str],
    mutation: AbstractSet[str],
    *,
    witnesses: tuple[AbstractSet[str], AbstractSet[str]],
) -> RecipeOracle:
    """Joins recipe memberships with the canonical and mutation witnesses."""
    return RecipeOracle(
        frozenset(canonical) | witnesses[0], frozenset(mutation) | witnesses[1]
    )


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
