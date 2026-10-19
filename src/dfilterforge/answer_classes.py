"""The error class of a scored answer and the proximity of a case to training.

``docs/protocol.md`` registers both (Training rules, amended 2026-10-18:
descriptive analyses of the self-served rows). They were defined after seed
2026's test scores were known, so they are post hoc: they describe answers
and decide nothing. Where this module and that text differ, the text holds.

An error class compares sets taken from an answer's IR and the gold IR. A
case's atoms are the predicates of its gold IR, negation and grouping
ignored, each in canonical form (``in`` lists sorted), and its proximity
stratum compares them with each training target's atoms. The callers pass
every IR in; nothing here reads gold or training files.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import StrEnum
import itertools

from dfilterforge.canonical import canonical_json
from dfilterforge.intent_ir import Expression
from dfilterforge.intent_ir import walk_predicates
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import OutcomeV1
from dfilterforge.train_combos import canonical_expression
from dfilterforge.train_combos import canonical_key

Atoms = frozenset[str]
Difference = Callable[[Expression, Expression], bool]


class ErrorClass(StrEnum):
    """The registered classes, in the order the first that applies wins."""

    PROVIDER_FAILED = "provider_failed"
    TRUNCATED = "truncated"
    MALFORMED = "malformed"
    ABSTAINED = "abstained"
    UNKNOWN_FIELD = "unknown_field"
    INVALID_OTHER = "invalid_other"
    SHORTCUT = "shortcut"
    MISSING_FIELD = "missing_field"
    EXTRA_FIELD = "extra_field"
    OPERATOR = "operator"
    VALUE = "value"
    STRUCTURE = "structure"
    SAME_FORM = "same_form"


class Proximity(StrEnum):
    """The registered strata, in the order the first that applies wins."""

    SAME_ATOMS = "same_atoms"
    INSIDE_ONE_TARGET = "inside_one_target"
    PAIRS_SEEN = "pairs_seen"
    APART = "apart"


# A malformed reply that stopped at the token limit is truncated.
_LENGTH = "length"
_UNKNOWN_FIELD = "unknown_field"
# The classes an outcome takes without reading an IR.
_BY_OUTCOME = {
    OutcomeV1.PROVIDER_FAILED: ErrorClass.PROVIDER_FAILED,
    OutcomeV1.ABSTAINED: ErrorClass.ABSTAINED,
    OutcomeV1.SHORTCUT: ErrorClass.SHORTCUT,
}


def fields(expression: Expression) -> frozenset[str]:
    """The field names an expression tests."""
    return frozenset(
        predicate.field for _, predicate in walk_predicates(expression)
    )


def _pairs(expression: Expression) -> frozenset[tuple[str, str]]:
    return frozenset(
        (predicate.field, predicate.operator.value)
        for _, predicate in walk_predicates(expression)
    )


def atoms(expression: Expression) -> Atoms:
    """Each predicate's canonical JSON, negation and grouping ignored."""
    return frozenset(
        canonical_json(canonical_expression(predicate))
        for _, predicate in walk_predicates(expression)
    )


# How a silent-wrong answer can differ from its gold, in the registered
# order; an answer that differs in none has the gold's canonical form.
_DIFFERENCES: tuple[tuple[ErrorClass, Difference], ...] = (
    (
        ErrorClass.MISSING_FIELD,
        lambda answer, gold: not fields(gold) <= fields(answer),
    ),
    (
        ErrorClass.EXTRA_FIELD,
        lambda answer, gold: not fields(answer) <= fields(gold),
    ),
    (ErrorClass.OPERATOR, lambda answer, gold: _pairs(answer) != _pairs(gold)),
    (ErrorClass.VALUE, lambda answer, gold: atoms(answer) != atoms(gold)),
    (
        ErrorClass.STRUCTURE,
        lambda answer, gold: canonical_key(answer) != canonical_key(gold),
    ),
)


def error_class(
    item: ItemOutcomeV1, answer: Expression | None, gold: Expression
) -> ErrorClass:
    """Returns the first registered class that applies to one answer.

    Args:
        item: A scored ready item that is not strong exact.
        answer: The expression of the answer's stored IR, None when it has
            none.
        gold: The expression of the case's gold IR.

    Returns:
        The class.

    Raises:
        ValueError: The item is strong exact or false ready, which take no
            class, or it is silent-wrong without a stored IR.
    """
    outcome = item.outcome
    if outcome in _BY_OUTCOME:
        return _BY_OUTCOME[outcome]
    if outcome is OutcomeV1.MALFORMED:
        if item.finish_reason == _LENGTH:
            return ErrorClass.TRUNCATED
        return ErrorClass.MALFORMED
    if outcome is OutcomeV1.INVALID:
        if item.error_code == _UNKNOWN_FIELD:
            return ErrorClass.UNKNOWN_FIELD
        return ErrorClass.INVALID_OTHER
    if outcome is not OutcomeV1.SILENT_WRONG:
        raise ValueError(f"{item.item_id} is {outcome.value}: no class")
    if answer is None:
        raise ValueError(f"{item.item_id} is silent-wrong without an IR")
    return next(
        (kind for kind, differs in _DIFFERENCES if differs(answer, gold)),
        ErrorClass.SAME_FORM,
    )


def proximity(case: Atoms, targets: Sequence[Atoms]) -> Proximity:
    """Returns the first registered stratum that applies to a case's atoms.

    No target joins two atoms on one field, so a case that does is apart by
    construction. A case of one atom that no target holds has no two atoms
    to see apart, so the registered wording puts it in pairs_seen; every
    atom of the committed test cases is in some target, so none is.

    Args:
        case: The atoms of the case's gold IR.
        targets: The atoms of each ready training target.

    Returns:
        The stratum.
    """
    if any(target == case for target in targets):
        return Proximity.SAME_ATOMS
    if any(case < target for target in targets):
        return Proximity.INSIDE_ONE_TARGET
    if all(
        any(set(pair) <= target for target in targets)
        for pair in itertools.combinations(case, 2)
    ):
        return Proximity.PAIRS_SEEN
    return Proximity.APART


def nearest(case: Atoms, targets: Sequence[Atoms]) -> int:
    """The index of the target a page shows beside a case.

    The target sharing the most atoms with the case, then the one with the
    fewest atoms on either side alone, then the earliest. This picks the
    example only; the stratum comes from :func:`proximity`.

    Raises:
        ValueError: There are no targets.
    """
    if not targets:
        raise ValueError("there are no training targets")
    return min(
        range(len(targets)),
        key=lambda index: (
            -len(case & targets[index]),
            len(case ^ targets[index]),
            index,
        ),
    )
