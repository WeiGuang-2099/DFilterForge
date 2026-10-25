"""Tests that the typed-IR response schema admits what the parser accepts.

The schema row of the self-served ladder sends this schema to the server's
grammar engine, so an answer the parser would accept must stay reachable:
every gold answer and every training target validates, and on hand-built
answers the schema and the parser agree except where JSON Schema cannot
follow the parser, which is listed here.
"""

import gzip
import json
from pathlib import Path
from typing import Any, cast, get_args, Protocol

from jsonschema import Draft202012Validator
import pytest

from dfilterforge.answer_schema import response_format
from dfilterforge.answer_schema import schema_names
from dfilterforge.answer_schema import typed_ir_schema
from dfilterforge.answer_schema import TYPED_IR_V1
from dfilterforge.completions import RequestSettingsV1
from dfilterforge.generation import GenerationError
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import parse_response
from dfilterforge.intent_ir import FIELD_NAME_PATTERN
from dfilterforge.intent_ir import GenerationResultV1
from dfilterforge.intent_ir import GenerationStatus
from dfilterforge.model_cases import model_non_ready_cases
from dfilterforge.model_split import model_semantic_cases

_DATA = Path(__file__).resolve().parents[1] / "data" / "train" / "v1"
# Keywords xgrammar 0.2.8 compiles as written; anything else it loosens,
# ignores or hands to another engine.
_EXACT_KEYWORDS = frozenset(
    {
        "$defs",
        "$ref",
        "additionalProperties",
        "anyOf",
        "const",
        "enum",
        "items",
        "maxItems",
        "minItems",
        "pattern",
        "properties",
        "required",
        "type",
    }
)


class _Validator(Protocol):
    """The one jsonschema method these tests call, typed."""

    def is_valid(self, instance: Any) -> bool:
        """Reports whether ``instance`` fits the schema."""
        ...


_VALIDATOR = cast(_Validator, Draft202012Validator(typed_ir_schema()))


_Json = dict[str, Any]


def _predicate(operator: str, value: object = None, **extra: object) -> _Json:
    node: _Json = {"kind": "predicate", "field": "ip.src", "operator": operator}
    if value is not None:
        node["value"] = value
    return node | extra


def _ready(expression: object, **extra: object) -> _Json:
    return {"status": "ready", "intent_ir": {"expression": expression}} | extra


def _without_exists_value(node: object) -> object:
    """Drops the null value of exists, as the SFT completions write it."""
    if isinstance(node, dict):
        mapping = cast(_Json, node)
        return {
            key: _without_exists_value(value)
            for key, value in mapping.items()
            if not (key == "value" and mapping.get("operator") == "exists")
        }
    if isinstance(node, list):
        return [_without_exists_value(item) for item in cast(list[Any], node)]
    return node


def _parser_accepts(answer: object) -> bool:
    try:
        parse_response(OutputContractV1.TYPED_IR, json.dumps(answer))
    except GenerationError:
        return False
    return True


def _schema_accepts(answer: object) -> bool:
    return _VALIDATOR.is_valid(answer)


def _keywords(schema: object) -> set[str]:
    """Collects the keywords of every subschema, not property names."""
    found: set[str] = set()
    if isinstance(schema, list):
        for item in cast(list[Any], schema):
            found |= _keywords(item)
    elif isinstance(schema, dict):
        for key, value in cast(_Json, schema).items():
            found.add(key)
            if key in ("properties", "$defs"):
                for subschema in cast(_Json, value).values():
                    found |= _keywords(subschema)
            elif key not in ("const", "enum", "required", "pattern"):
                found |= _keywords(value)
    return found


def test_the_schema_is_well_formed_and_uses_only_exact_keywords() -> None:
    Draft202012Validator.check_schema(typed_ir_schema())

    assert _keywords(typed_ir_schema()) <= _EXACT_KEYWORDS


def test_the_request_names_one_schema_the_settings_admit() -> None:
    settings_names = get_args(
        get_args(RequestSettingsV1.model_fields["response_schema"].annotation)[
            0
        ]
    )

    assert settings_names == schema_names() == (TYPED_IR_V1,)
    assert response_format(TYPED_IR_V1) == {
        "type": "json_schema",
        "json_schema": {
            "name": "generation_result",
            "schema": typed_ir_schema(),
            "strict": True,
        },
    }


def test_every_ready_gold_answer_is_reachable() -> None:
    """Each gold IR, with exists written either way, fits the schema."""
    for case in model_semantic_cases():
        answer = GenerationResultV1(
            status=GenerationStatus.READY, intent_ir=case.canonical_ir
        ).model_dump(mode="json")
        for form in (answer, _without_exists_value(answer)):
            assert _schema_accepts(form), case.case_id
            assert _parser_accepts(form), case.case_id


def test_every_non_ready_gold_answer_is_reachable() -> None:
    for case in model_non_ready_cases():
        clarifying = case.status == "needs_clarification"
        answer = GenerationResultV1(
            status=GenerationStatus(case.status),
            clarifying_question="Which one?" if clarifying else None,
            missing_slots=case.missing_slots,
        ).model_dump(mode="json")

        assert _schema_accepts(answer), case.case_id
        assert _parser_accepts(answer), case.case_id


def test_every_training_target_is_reachable() -> None:
    """Both stored forms of all 1,299 v1 targets fit the schema."""
    lines = (_DATA / "train.jsonl").read_text("utf-8").splitlines()
    with gzip.open(_DATA / "sft.jsonl.gz", "rt", encoding="utf-8") as sft:
        completions = [json.loads(line)["completion"] for line in sft]

    targets = [json.loads(line)["target"] for line in lines]
    assert len(targets) == len(completions) == 1299
    for target in targets:
        assert _schema_accepts(target), target
    for completion in completions:
        assert _schema_accepts(json.loads(completion)), completion


_DEEP = {
    "kind": "not",
    "child": {
        "kind": "not",
        "child": {
            "kind": "all",
            "children": [_predicate("exists"), _predicate("exists")],
        },
    },
}


@pytest.mark.parametrize(
    ("answer", "accepted"),
    [
        (_ready(_predicate("exists")), True),
        (_ready(_predicate("exists") | {"value": None}), True),
        (
            {
                "schema_version": "1.0",
                "status": "ready",
                "assumptions": ["outbound only"],
                "clarifying_question": None,
                "missing_slots": [],
                "intent_ir": {
                    "ir_schema_version": "1.0",
                    "scope": "packet",
                    "expression": _predicate("eq", 1.5),
                },
            },
            True,
        ),
        (_ready(_predicate("in", [1, "a", True])), True),
        (_ready(_predicate("in_subnet", "10.0.0.0/8")), True),
        (_ready(_predicate("in_subnet", "10.0.0.1")), True),
        (_ready(_predicate("in_subnet", "10.0.0.0/255.0.0.0")), True),
        (_ready(_predicate("in_subnet", "fe80::/10")), True),
        (_ready(_predicate("in_subnet", "10.0.0.0/08")), True),
        (_ready(_predicate("in_subnet", "fe80::/064")), True),
        (_ready(_predicate("in_subnet", "fe80::1%eth0/64")), True),
        (_ready(_predicate("in_subnet", "fe80::1%1")), True),
        (_ready(_predicate("contains", "GET")), True),
        (_ready(_predicate("ge", False)), True),
        (_ready(_DEEP), True),
        (
            {
                "status": "needs_clarification",
                "clarifying_question": " ",
                "missing_slots": ["port", "address"],
            },
            True,
        ),
        ({"status": "needs_clarification", "clarifying_question": "?"}, True),
        ({"status": "not_expressible"}, True),
        (_ready({"kind": "all", "children": [_predicate("exists")]}), False),
        (_ready(_predicate("exists", 1)), False),
        (_ready(_predicate("exists") | {"kind": "leaf"}), False),
        (_ready({"field": "ip.src", "operator": "exists"}), False),
        (_ready(_predicate("in_subnet", "not-a-cidr")), False),
        (_ready(_predicate("in_subnet", "10.0.0.0/33")), False),
        (_ready(_predicate("matches", "x")), False),
        (_ready(_predicate("eq", [1])), False),
        (_ready(_predicate("eq")), False),
        (_ready(_predicate("in", [])), False),
        (_ready(_predicate("in", [[1]])), False),
        (_ready(_predicate("contains", 7)), False),
        (_ready(_predicate("exists") | {"field": "ip src"}), False),
        (_ready(_predicate("exists"), clarifying_question="Which?"), False),
        (_ready(_predicate("exists"), missing_slots=["port"]), False),
        (_ready(_predicate("exists"), notes="extra"), False),
        (_ready(_predicate("exists"), schema_version="2.0"), False),
        ({"status": "ready"}, False),
        ({"status": "ready", "intent_ir": None}, False),
        ({"status": "needs_clarification"}, False),
        (
            {
                "status": "needs_clarification",
                "clarifying_question": "?",
                "missing_slots": ["host"],
            },
            False,
        ),
        (
            {
                "status": "needs_clarification",
                "clarifying_question": "?",
                "intent_ir": {"expression": _predicate("exists")},
            },
            False,
        ),
        ({"status": "not_expressible", "missing_slots": ["port"]}, False),
        ({"status": "not_expressible", "clarifying_question": "?"}, False),
        ({"status": "unsure"}, False),
        (["ready"], False),
    ],
)
def test_the_schema_and_the_parser_agree(
    answer: object, accepted: bool
) -> None:
    assert _parser_accepts(answer) is accepted
    assert _schema_accepts(answer) is accepted


@pytest.mark.parametrize(
    "answer",
    [
        # uniqueItems is left out of the schema.
        {
            "status": "needs_clarification",
            "clarifying_question": "?",
            "missing_slots": ["port", "port"],
        },
        # The in_subnet pattern admits any colon run as an IPv6 address.
        _ready(_predicate("in_subnet", "1:2:3")),
        # A dotted suffix may be any address, not only a mask.
        _ready(_predicate("in_subnet", "10.0.0.0/1.2.3.4")),
        # minLength would cost the question its JSON escapes.
        {"status": "needs_clarification", "clarifying_question": ""},
        # xgrammar drops maxLength beside a pattern, so none is set.
        # Nesting past pydantic's recursion guard passes the schema too;
        # the guard's depth moves with platform and stack (99 levels on
        # Windows, more on Linux), so no case pins it.
        _ready(_predicate("exists") | {"field": "a" * 257}),
    ],
)
def test_the_schema_is_looser_than_the_parser_only_where_listed(
    answer: object,
) -> None:
    assert not _parser_accepts(answer)
    assert _schema_accepts(answer)


def test_the_schema_is_stricter_than_the_parser_only_on_zone_ids() -> None:
    """A zone id may hold only characters a pattern can match unescaped."""
    answer = _ready(_predicate("in_subnet", "fe80::1%a b"))

    assert _parser_accepts(answer)
    assert not _schema_accepts(answer)


@pytest.mark.parametrize(
    "name",
    [
        "ip.src",
        "tcp.flags.syn",
        "http.request.method",
        "sip.Method",
        "a-b.c_d9",
        "_",
        "ip..src",
        ".ip",
        "ip.",
        "ip src",
        "ip/src",
        "a-",
    ],
)
def test_the_field_pattern_matches_the_parser(name: str) -> None:
    answer = _ready(_predicate("exists") | {"field": name})

    assert _schema_accepts(answer) is bool(FIELD_NAME_PATTERN.fullmatch(name))
