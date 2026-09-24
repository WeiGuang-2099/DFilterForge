"""Single-site mutants: one family per test, fixed order, valid IR only."""

from pydantic import ValidationError
import pytest

from dfilterforge import mutants
from dfilterforge.compiler import compile_intent
from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import AnyOf
from dfilterforge.intent_ir import Expression
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Not
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.intent_ir import ScalarValue
from dfilterforge.model_split import model_semantic_cases
from dfilterforge.model_split import MUTANT_WAIVERS
from dfilterforge.mutants import Mutant
from dfilterforge.mutants import MutantCategory
from dfilterforge.mutants import MutantWaiver
from dfilterforge.mutants import single_site_mutants


def _p(
    field: str,
    operator: Operator = Operator.EXISTS,
    value: ScalarValue | None = None,
) -> Predicate:
    return Predicate(field=field, operator=operator, value=value)


def _mutants(expression: Expression) -> tuple[Mutant, ...]:
    return single_site_mutants(IntentIrV1(expression=expression))


def _texts(
    expression: Expression, category: MutantCategory | None = None
) -> list[tuple[str, str]]:
    """Returns (edit label, compiled filter) pairs, optionally of one family."""
    return [
        (mutant.edit, compile_intent(mutant.intent))
        for mutant in _mutants(expression)
        if category is None or mutant.category is category
    ]


def test_field_swaps_move_one_sided_fields_and_ecn_flags() -> None:
    assert _texts(_p("udp.dstport", Operator.EQ, 53)) == [
        ("root: udp.dstport -> udp.port", "udp.port == 53"),
        ("root: udp.dstport -> udp.srcport", "udp.srcport == 53"),
    ]
    assert _texts(_p("ip.dst", Operator.IN_SUBNET, "192.0.2.0/24"))[:2] == [
        ("root: ip.dst -> ip.addr", "ip.addr == 192.0.2.0/24"),
        ("root: ip.dst -> ip.src", "ip.src == 192.0.2.0/24"),
    ]
    assert _texts(_p("tcp.flags.cwr", Operator.EQ, True)) == [
        ("root: tcp.flags.cwr -> tcp.flags.ece", "tcp.flags.ece == true"),
    ]


@pytest.mark.parametrize(
    ("field", "value", "label", "text"),
    [
        (
            "tcp.flags.ack",
            True,
            "root: tcp.flags.ack eq true -> tcp.ack eq 1",
            "tcp.ack == 1",
        ),
        (
            "tcp.flags.ack",
            False,
            "root: tcp.flags.ack eq false -> tcp.ack eq 0",
            "tcp.ack == 0",
        ),
        (
            "tcp.flags.syn",
            True,
            "root: tcp.flags.syn eq true -> tcp.seq eq 0",
            "tcp.seq == 0",
        ),
        (
            "tcp.flags.syn",
            False,
            "root: tcp.flags.syn eq false -> tcp.seq ne 0",
            "tcp.seq != 0",
        ),
    ],
)
def test_flag_as_number_reads_a_flag_as_its_number_field(
    field: str, value: bool, label: str, text: str
) -> None:
    expression = _p(field, Operator.EQ, value)

    assert _texts(expression) == [(label, text)]
    assert [mutant.category for mutant in _mutants(expression)] == [
        MutantCategory.FLAG_AS_NUMBER
    ]


def test_flag_as_number_needs_boolean_equality() -> None:
    # An integer flag value is not the canonical form, and a boolean is
    # never treated as an integer bound.
    assert not _mutants(_p("tcp.flags.ack", Operator.EQ, 1))
    assert not _mutants(_p("tcp.flags.syn", Operator.NE, True))
    assert not _mutants(_p("tcp.flags.fin", Operator.EQ, True))


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("dns.qry.type", 1, [("root: dns.qry.type eq 1 -> ne 28", "!= 28")]),
        ("dns.qry.type", 28, [("root: dns.qry.type eq 28 -> ne 1", "!= 1")]),
        (
            "dns.flags.rcode",
            0,
            [
                ("root: dns.flags.rcode eq 0 -> ne 3", "!= 3"),
                ("root: dns.flags.rcode eq 0 -> lt 3", "< 3"),
            ],
        ),
        (
            "dns.flags.rcode",
            3,
            [
                ("root: dns.flags.rcode eq 3 -> ne 0", "!= 0"),
                ("root: dns.flags.rcode eq 3 -> gt 0", "> 0"),
            ],
        ),
        ("dns.qry.type", 5, []),
    ],
)
def test_value_domain_rewrites_one_dns_code_as_its_complement(
    field: str, value: int, expected: list[tuple[str, str]]
) -> None:
    assert _texts(_p(field, Operator.EQ, value)) == [
        (label, f"{field} {suffix}") for label, suffix in expected
    ]


def test_value_domain_applies_to_equality_only() -> None:
    assert _texts(_p("dns.qry.type", Operator.NE, 1)) == [
        ("root: dns.qry.type ne 1 -> lt 1", "dns.qry.type < 1"),
        ("root: dns.qry.type ne 1 -> gt 1", "dns.qry.type > 1"),
    ]


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        (Operator.LE, 1, ["lt 1", "eq 1", "le 2", "le 0"]),
        (Operator.GE, 64, ["gt 64", "eq 64", "ge 65", "ge 63"]),
        (Operator.GT, 5353, ["ge 5353", "gt 5354", "gt 5352"]),
        (Operator.LT, 5353, ["le 5353", "lt 5354", "lt 5352"]),
        (Operator.NE, 443, ["lt 443", "gt 443"]),
        (Operator.EQ, 443, []),
    ],
)
def test_boundaries_shift_integer_comparisons_by_one(
    operator: Operator, value: int, expected: list[str]
) -> None:
    mutated = _mutants(_p("frame.len", operator, value))

    assert [mutant.edit for mutant in mutated] == [
        f"root: frame.len {operator.value} {value} -> {change}"
        for change in expected
    ]
    assert all(mutant.category is MutantCategory.BOUNDARY for mutant in mutated)


@pytest.mark.parametrize(
    ("network", "expected"),
    [
        ("10.0.0.0/8", ["0.0.0.0/0", "10.0.0.0/9", "10.1.0.0/16"]),
        ("192.0.2.0/24", ["192.0.0.0/16", "192.0.2.0/25"]),
        ("198.51.100.7/32", ["198.51.100.0/24"]),
        ("224.0.0.0/4", ["224.0.0.0/5", "224.16.0.0/12"]),
        # Host bits are accepted by the IR and keep their original label.
        ("10.1.2.3/8", ["0.0.0.0/0", "10.0.0.0/9", "10.1.0.0/16"]),
    ],
)
def test_subnets_widen_by_a_byte_and_narrow_by_a_bit_or_a_byte(
    network: str, expected: list[str]
) -> None:
    expression = _p("ip.addr", Operator.IN_SUBNET, network)

    assert _texts(expression) == [
        (f"root: ip.addr {network} -> {other}", f"ip.addr == {other}")
        for other in expected
    ]


def test_drop_conjunct_keeps_a_group_of_the_rest_or_the_last_child() -> None:
    first, second, third = _p("tcp"), _p("udp"), _p("dns")

    assert _texts(
        All(children=(first, second)), MutantCategory.DROP_CONJUNCT
    ) == [
        ("root: drop child 0", "udp"),
        ("root: drop child 1", "tcp"),
    ]
    assert _texts(
        All(children=(first, second, third)), MutantCategory.DROP_CONJUNCT
    ) == [
        ("root: drop child 0", "(udp && dns)"),
        ("root: drop child 1", "(tcp && dns)"),
        ("root: drop child 2", "(tcp && udp)"),
    ]


def test_drop_disjunct_keeps_the_group_kind() -> None:
    expression = AnyOf(children=(_p("tcp"), _p("udp"), _p("dns")))

    assert _texts(expression, MutantCategory.DROP_DISJUNCT) == [
        ("root: drop child 0", "(udp || dns)"),
        ("root: drop child 1", "(tcp || dns)"),
        ("root: drop child 2", "(tcp || udp)"),
    ]


def test_drop_not_removes_the_negation_and_inner_edits_keep_it() -> None:
    expression = Not(child=_p("ip.src", Operator.IN_SUBNET, "192.0.2.0/24"))

    assert _texts(expression) == [
        ("root: drop not", "ip.src == 192.0.2.0/24"),
        ("0: ip.src -> ip.addr", "!(ip.addr == 192.0.2.0/24)"),
        ("0: ip.src -> ip.dst", "!(ip.dst == 192.0.2.0/24)"),
        ("0: ip.src 192.0.2.0/24 -> 192.0.0.0/16", "!(ip.src == 192.0.0.0/16)"),
        ("0: ip.src 192.0.2.0/24 -> 192.0.2.0/25", "!(ip.src == 192.0.2.0/25)"),
    ]


def test_nested_edits_come_in_preorder_with_their_node_paths() -> None:
    expression = AnyOf(
        children=(
            All(
                children=(
                    _p("tcp.flags.syn", Operator.EQ, True),
                    _p("tcp.flags.ece", Operator.EQ, True),
                )
            ),
            _p("ip.ttl", Operator.LE, 1),
        )
    )

    assert [
        (mutant.category.value, mutant.edit) for mutant in _mutants(expression)
    ] == [
        ("drop-disjunct", "root: drop child 0"),
        ("drop-conjunct", "0: drop child 0"),
        ("flag-as-number", "0.0: tcp.flags.syn eq true -> tcp.seq eq 0"),
        ("drop-conjunct", "0: drop child 1"),
        ("field-swap", "0.1: tcp.flags.ece -> tcp.flags.cwr"),
        ("drop-disjunct", "root: drop child 1"),
        ("boundary", "1: ip.ttl le 1 -> lt 1"),
        ("boundary", "1: ip.ttl le 1 -> eq 1"),
        ("boundary", "1: ip.ttl le 1 -> le 2"),
        ("boundary", "1: ip.ttl le 1 -> le 0"),
    ]
    assert compile_intent(_mutants(expression)[4].intent) == (
        "((tcp.flags.syn == true && tcp.flags.cwr == true) || ip.ttl <= 1)"
    )


def test_a_predicate_yields_its_families_in_a_fixed_order() -> None:
    mutated = _mutants(_p("ip.src", Operator.IN_SUBNET, "10.0.0.0/8"))

    assert [mutant.category for mutant in mutated] == [
        MutantCategory.FIELD_SWAP,
        MutantCategory.FIELD_SWAP,
        MutantCategory.SUBNET,
        MutantCategory.SUBNET,
        MutantCategory.SUBNET,
    ]
    assert not _mutants(_p("tcp"))


def test_model_cases_give_unique_labels_and_real_single_site_changes() -> None:
    total = 0
    for case in model_semantic_cases():
        first = single_site_mutants(case.canonical_ir)
        second = single_site_mutants(case.canonical_ir)
        edits = [mutant.edit for mutant in first]

        assert first == second
        assert len(set(edits)) == len(edits)
        assert all(mutant.intent != case.canonical_ir for mutant in first)
        assert all(
            IntentIrV1.model_validate(mutant.intent.model_dump(mode="json"))
            == mutant.intent
            for mutant in first
        )
        total += len(first)
    # mutants.generated in the Simplified receipt,
    # docs/ablations/evidence/005-probe-adequacy-simplified.json.
    assert total == 182


def test_invalid_mutants_are_skipped_and_the_rest_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mutants,
        "FIELD_SWAPS",
        {"tcp.dstport": ("tcp..port", "tcp.port", "tcp port")},
    )
    monkeypatch.setattr(
        mutants,
        "FLAG_AS_NUMBER",
        {("tcp.flags.ack", True): ("tcp.ack!", Operator.EQ, 1)},
    )
    expression = All(
        children=(
            _p("tcp.flags.ack", Operator.EQ, True),
            _p("tcp.dstport", Operator.EQ, 443),
        )
    )

    assert _texts(expression) == [
        ("root: drop child 0", "tcp.dstport == 443"),
        ("root: drop child 1", "tcp.flags.ack == true"),
        (
            "1: tcp.dstport -> tcp.port",
            "(tcp.flags.ack == true && tcp.port == 443)",
        ),
    ]


def test_waivers_are_typed_and_reasoned() -> None:
    waiver = MutantWaiver(
        case_id="private-either-endpoint",
        edit="0: ip.src -> ip.addr",
        display_filter="(ip.addr == 10.0.0.0/8 || ip.dst == 10.0.0.0/8)",
        kind="equivalent",
        reason="Either endpoint in 10/8 is what the request asks for.",
    )

    assert waiver.kind == "equivalent"
    for bad in (
        {"case_id": "Bad Case"},
        {"edit": ""},
        {"display_filter": ""},
        {"kind": "unsure"},
        {"reason": ""},
    ):
        with pytest.raises(ValidationError):
            MutantWaiver.model_validate({**waiver.model_dump(), **bad})


def test_every_gold_waiver_names_a_mutant_of_its_case() -> None:
    cases = {case.case_id: case for case in model_semantic_cases()}
    keys = [(waiver.case_id, waiver.edit) for waiver in MUTANT_WAIVERS]

    assert len(set(keys)) == len(keys)
    for waiver in MUTANT_WAIVERS:
        assert waiver.case_id in cases
        # The label and the filter must name the same mutant, so a label
        # that moves to another mutant fails here, not only in the gate.
        assert (waiver.edit, waiver.display_filter) in {
            (mutant.edit, compile_intent(mutant.intent))
            for mutant in single_site_mutants(
                cases[waiver.case_id].canonical_ir
            )
        }
