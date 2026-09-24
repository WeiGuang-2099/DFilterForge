"""Shortcut policy: what a candidate mentions and which rules it breaks."""

import ipaddress

import pytest

from dfilterforge.catalog_runtime import DEFAULT_CATALOG_PATH
from dfilterforge.catalog_runtime import tshark_types
from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import AnyOf
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Not
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.intent_ir import ScalarValue
from dfilterforge.model_split import model_semantic_cases
from dfilterforge.shortcuts import find_shortcuts
from dfilterforge.shortcuts import references
from dfilterforge.shortcuts import ShortcutHitV1
from dfilterforge.shortcuts import ShortcutRule

_POSITION = ShortcutRule.CAPTURE_POSITION
_GENERATOR = ShortcutRule.GENERATOR_IDENTIFIER
_CONSTANT = ShortcutRule.CAPTURE_CONSTANT
_TYPES = {
    "dns.response_in": "FT_FRAMENUM",
    "tcp.time_delta": "FT_RELATIVE_TIME",
    "tcp.port": "FT_UINT16",
}
_CATALOG = pytest.mark.skipif(
    not DEFAULT_CATALOG_PATH.exists(),
    reason="the frozen catalog ships in the Docker image",
)


def _p(
    field: str,
    operator: Operator = Operator.EXISTS,
    value: ScalarValue | tuple[ScalarValue, ...] | None = None,
) -> Predicate:
    return Predicate(field=field, operator=operator, value=value)


def _hits(
    candidate: IntentIrV1 | str, request: str = "Show some packets."
) -> list[tuple[ShortcutRule, str]]:
    found = find_shortcuts(references(candidate), request, _TYPES)
    return [(hit.rule, hit.token) for hit in found]


def test_a_display_filter_is_scanned_outside_its_quoted_strings() -> None:
    found = references(
        'tcp.port in {41000..41002 443} && dns.qry.name == "frame.number"'
        " || eth.src == 02:00:00:00:00:01 or ip.dst == 10.0.0.0/8"
        " && tcp.flags == 0x12"
    )

    assert found.fields == (
        "tcp.port",
        "dns.qry.name",
        "eth.src",
        "ip.dst",
        "tcp.flags",
    )
    assert found.numbers == (
        ("41000", 41000),
        ("41002", 41002),
        ("443", 443),
        ("0x12", 18),
    )
    assert found.addresses == (
        ("10.0.0.0/8", ipaddress.IPv4Network("10.0.0.0/8")),
    )
    assert found.macs == ("02:00:00:00:00:01",)
    assert found.strings == ("frame.number",)
    assert found.disjunctions == 2


def test_a_typed_ir_counts_or_like_its_display_filter() -> None:
    intent = IntentIrV1(
        expression=AnyOf(
            children=(
                All(
                    children=(
                        _p("ip.src", Operator.IN_SUBNET, "192.0.2.0/24"),
                        _p("udp.dstport", Operator.IN, (53, 41170)),
                    )
                ),
                Not(child=AnyOf(children=(_p("tcp"), _p("udp"), _p("dns")))),
            )
        )
    )

    found = references(intent)

    assert found.fields == ("ip.src", "udp.dstport", "tcp", "udp", "dns")
    assert found.numbers == (("53", 53), ("41170", 41170))
    assert [text for text, _ in found.addresses] == ["192.0.2.0/24"]
    assert found.disjunctions == 3
    three = AnyOf(children=(_p("tcp"), _p("udp"), _p("dns")))
    assert references(IntentIrV1(expression=three)).disjunctions == 2
    assert references("tcp || udp or dns").disjunctions == 2


@pytest.mark.parametrize(
    "candidate",
    [
        "frame.number == 12",
        "frame.time_delta > 0.5",
        "_ws.expert",
        "tcp.stream == 3",
        "udp.stream.pnum == 1",
        # Known only by its catalog type.
        "dns.response_in",
        "tcp.time_delta < 1",
    ],
)
def test_capture_position_fields_are_shortcuts(candidate: str) -> None:
    assert [rule for rule, _ in _hits(candidate)] == [_POSITION]


def test_type_rules_need_the_catalog_type() -> None:
    # Without its type, a frame reference reads as an ordinary field.
    found = references("dns.response_in == 7")

    assert not find_shortcuts(found, "", {})


@pytest.mark.parametrize(
    "candidate",
    ["frame.len > 60", 'frame.protocols contains "dns"', "frame", "tcp.port"],
)
def test_packet_describing_fields_are_not_shortcuts(candidate: str) -> None:
    assert not _hits(candidate)


@pytest.mark.parametrize(
    "candidate",
    ["ip.id == 110", "dns.id == 7", "tcp.checksum.status == 2", "tcp.seq_raw"],
)
def test_generator_identifiers_are_shortcuts(candidate: str) -> None:
    assert [rule for rule, _ in _hits(candidate)] == [_GENERATOR]


@pytest.mark.parametrize(
    ("candidate", "request_text", "expected"),
    [
        ("ip.src == 192.0.2.111", "", [(_CONSTANT, "192.0.2.111")]),
        ("ip.src == 10.1.2.3/32", "", [(_CONSTANT, "10.1.2.3/32")]),
        ("ip.src == 10.1.2.3", "Show traffic from 10.1.2.3.", []),
        ("ip.src == 198.51.100.0/24", "", [(_CONSTANT, "198.51.100.0/24")]),
        ("ip.src == 198.0.0.0/8", "", [(_CONSTANT, "198.0.0.0/8")]),
        ("ip.src == 198.51.100.0/24", "Sources in TEST-NET-2.", []),
        ("ip.dst == 10.0.0.0/8", "headed to a private 10/8 address", []),
        ("ip.src == 192.0.2.0/25", "", []),
        ("tcp.srcport == 41170", "", [(_CONSTANT, "41170")]),
        ("tcp.srcport == 0xa0d2", "", [(_CONSTANT, "0xa0d2")]),
        ("tcp.srcport == 41170", "Show port 41170.", []),
        ("tcp.dstport == 443", "", []),
        (
            "eth.src == 02:00:00:00:00:01",
            "",
            [(_CONSTANT, "02:00:00:00:00:01")],
        ),
        (
            'dns.qry.name == "probe-110-3.example"',
            "",
            [(_CONSTANT, "probe-110-3")],
        ),
        ('dns.qry.name == "example.com"', "", []),
    ],
)
def test_capture_constants_are_shortcuts_unless_the_request_states_them(
    candidate: str,
    request_text: str,
    expected: list[tuple[ShortcutRule, str]],
) -> None:
    assert _hits(candidate, request_text) == expected


def test_typed_values_are_checked_like_filter_literals() -> None:
    intent = IntentIrV1(
        expression=All(
            children=(
                _p("ip.dst", Operator.EQ, "198.51.100.23"),
                _p("udp.srcport", Operator.EQ, 41170),
                _p("dns.qry.name", Operator.EQ, "witness-110-54.example"),
            )
        )
    )

    assert _hits(intent) == [
        (_CONSTANT, "198.51.100.23"),
        (_CONSTANT, "41170"),
        (_CONSTANT, "witness-110-54"),
    ]


def test_hits_come_in_rule_order_once_each_and_bounded() -> None:
    long_name = "frame." + "x" * 80

    assert _hits(
        f"ip.id == 41170 || frame.number == 3 || ip.id == 7 || {long_name}"
    ) == [
        (_POSITION, "frame.number"),
        (_POSITION, long_name[:64]),
        (_GENERATOR, "ip.id"),
        (_CONSTANT, "41170"),
    ]
    with pytest.raises(ValueError):
        ShortcutHitV1(rule=_POSITION, token="")


@_CATALOG
def test_the_catalog_types_frame_references_and_times() -> None:
    types = tshark_types(
        ["dns.response_in", "frame.time_epoch", "tcp.port", "no.such.field"]
    )

    assert types == {
        "dns.response_in": "FT_FRAMENUM",
        "frame.time_epoch": "FT_ABSOLUTE_TIME",
        "tcp.port": "FT_UINT16",
    }


@_CATALOG
def test_no_gold_filter_or_target_breaks_a_rule() -> None:
    for case in model_semantic_cases():
        for candidate in (
            case.reference_filter,
            case.mutation_filter,
            case.canonical_ir,
        ):
            found = references(candidate)
            for request in case.paraphrases:
                assert not find_shortcuts(
                    found, request, tshark_types(found.fields)
                ), (case.case_id, candidate)
