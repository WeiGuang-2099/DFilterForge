"""The registered error classes and proximity strata, on hand-built IR."""

from __future__ import annotations

from typing import Any

import pytest

from dfilterforge.answer_classes import atoms
from dfilterforge.answer_classes import error_class
from dfilterforge.answer_classes import ErrorClass
from dfilterforge.answer_classes import nearest
from dfilterforge.answer_classes import proximity
from dfilterforge.answer_classes import Proximity
from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import AnyOf
from dfilterforge.intent_ir import Expression
from dfilterforge.intent_ir import Not
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import OutcomeV1

SYN = Predicate(field="tcp.flags.syn", operator=Operator.EQ, value=True)
ACK = Predicate(field="tcp.flags.ack", operator=Operator.EQ, value=True)
DNS = Predicate(field="udp.srcport", operator=Operator.EQ, value=53)
GOLD = All(children=(SYN, Not(child=ACK)))


def _item(outcome: OutcomeV1, **fields: Any) -> ItemOutcomeV1:
    return ItemOutcomeV1(
        condition="C4",
        item_id="mei-1001",
        case_id="syn-no-ack",
        outcome=outcome,
        gold_field_count=2,
        latency_ms=1.0,
        **fields,
    )


@pytest.mark.parametrize(
    ("outcome", "fields", "expected"),
    [
        (OutcomeV1.PROVIDER_FAILED, {}, ErrorClass.PROVIDER_FAILED),
        (
            OutcomeV1.MALFORMED,
            {"finish_reason": "length"},
            ErrorClass.TRUNCATED,
        ),
        (OutcomeV1.MALFORMED, {"finish_reason": "stop"}, ErrorClass.MALFORMED),
        (OutcomeV1.ABSTAINED, {}, ErrorClass.ABSTAINED),
        (
            OutcomeV1.INVALID,
            {"error_code": "unknown_field"},
            ErrorClass.UNKNOWN_FIELD,
        ),
        (
            OutcomeV1.INVALID,
            {"error_code": "type_mismatch"},
            ErrorClass.INVALID_OTHER,
        ),
        (OutcomeV1.SHORTCUT, {}, ErrorClass.SHORTCUT),
    ],
)
def test_an_answer_that_is_not_silent_wrong_is_classed_by_its_outcome(
    outcome: OutcomeV1, fields: dict[str, Any], expected: ErrorClass
) -> None:
    assert error_class(_item(outcome, **fields), None, GOLD) is expected


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        # Missing a gold field wins over the extra field it also has.
        (All(children=(SYN, Not(child=DNS))), ErrorClass.MISSING_FIELD),
        (All(children=(SYN, Not(child=ACK), DNS)), ErrorClass.EXTRA_FIELD),
        (
            All(
                children=(
                    SYN,
                    Predicate(
                        field="tcp.flags.ack", operator=Operator.NE, value=True
                    ),
                )
            ),
            ErrorClass.OPERATOR,
        ),
        (
            All(
                children=(
                    SYN,
                    Not(child=ACK.model_copy(update={"value": False})),
                )
            ),
            ErrorClass.VALUE,
        ),
        # Negation is ignored until the canonical forms are compared.
        (All(children=(SYN, ACK)), ErrorClass.STRUCTURE),
        (AnyOf(children=(SYN, Not(child=ACK))), ErrorClass.STRUCTURE),
        # The same canonical form in another order.
        (All(children=(Not(child=ACK), SYN)), ErrorClass.SAME_FORM),
    ],
)
def test_a_silent_wrong_answer_takes_the_first_difference_from_its_gold(
    answer: Expression, expected: ErrorClass
) -> None:
    item = _item(OutcomeV1.SILENT_WRONG)

    assert error_class(item, answer, GOLD) is expected


def test_strong_exact_and_a_silent_wrong_answer_without_ir_take_no_class() -> (
    None
):
    with pytest.raises(ValueError, match="no class"):
        error_class(_item(OutcomeV1.STRONG_EXACT), GOLD, GOLD)
    with pytest.raises(ValueError, match="without an IR"):
        error_class(_item(OutcomeV1.SILENT_WRONG), None, GOLD)


def test_atoms_ignore_negation_grouping_and_the_order_of_an_in_list() -> None:
    forward = Predicate(field="tcp.port", operator=Operator.IN, value=(80, 443))
    backward = forward.model_copy(update={"value": (443, 80)})

    assert atoms(AnyOf(children=(Not(child=forward), SYN))) == atoms(
        All(children=(SYN, backward))
    )


def _set(*predicates: Predicate) -> frozenset[str]:
    if len(predicates) == 1:
        return atoms(predicates[0])
    return atoms(All(children=predicates))


RST = Predicate(field="tcp.flags.reset", operator=Operator.EQ, value=True)
TARGETS = [_set(SYN, DNS), _set(SYN, ACK, RST), _set(ACK, DNS)]


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        (_set(DNS, SYN), Proximity.SAME_ATOMS),
        (_set(SYN, RST), Proximity.INSIDE_ONE_TARGET),
        # Every pair is in some target, all three in none.
        (_set(SYN, ACK, DNS), Proximity.PAIRS_SEEN),
        (_set(RST, DNS), Proximity.APART),
        # Two atoms on one field, which no target joins.
        (
            _set(DNS, DNS.model_copy(update={"value": 5353})),
            Proximity.APART,
        ),
        # One atom no target holds: every two of its atoms, of which there
        # are none, share a target, as the registered wording reads.
        (
            _set(
                Predicate(
                    field="tcp.flags.fin", operator=Operator.EQ, value=True
                )
            ),
            Proximity.PAIRS_SEEN,
        ),
    ],
)
def test_a_case_takes_the_first_stratum_its_atoms_reach(
    case: frozenset[str], expected: Proximity
) -> None:
    assert proximity(case, TARGETS) is expected


def test_the_shown_target_shares_most_then_differs_least_then_comes_first() -> (
    None
):
    targets = [_set(SYN, ACK, RST), _set(SYN, DNS), _set(DNS, SYN)]

    assert nearest(_set(SYN, DNS), targets) == 1
    assert nearest(_set(SYN), targets) == 1
    assert nearest(_set(ACK, RST), targets) == 0
    with pytest.raises(ValueError):
        nearest(_set(SYN), [])
