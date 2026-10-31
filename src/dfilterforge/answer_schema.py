"""JSON schemas that constrain a model's answer while it is decoded.

A schema row of the self-served ladder sends one of these as the request's
``response_format``, so the server's grammar engine can only emit answers
of the typed-IR envelope's shape. The schema states what the parser in
:mod:`dfilterforge.intent_ir` accepts, as far as JSON Schema can: the node
kinds, the operators and the value each one takes, and which payload each
status carries. It names no field, so an answer can still use a field the
catalog lacks or give a field a value of the wrong type; those answers stay
invalid, not malformed.

Only keywords that vLLM 0.21.0's default grammar engine, xgrammar 0.2.8,
compiles as written are used. allOf, oneOf, not and if/then/else are left
out because xgrammar loosens them without an error; uniqueItems because
vLLM hands it to another engine; minLength and maxLength because xgrammar
drops them beside a pattern and, alone, compiles a string that cannot
hold a JSON escape. A string with a pattern holds no escape either, so
patterns only describe values that need none. The schema is therefore
looser than the parser where the tests list it: missing_slots may repeat
a slot, a clarifying question may be empty, a field name may pass 256
bytes, an expression may nest deeper than pydantic's recursion guard
lets the parser read (a depth that moves with platform and stack), and
the in_subnet pattern admits some strings ``ipaddress`` rejects. It is
stricter in one place: an IPv6 zone id may hold only letters, digits,
'_', '.' and '-'. Recursion goes through a local
``$ref`` and ends at a predicate, with no depth bound. Properties are
declared in the order the typed-IR prompt lists them, because the engine
emits them in declared order. The client keeps that order on the wire;
test_a_response_schema_reaches_the_server_in_declared_order in
tests/test_model_client.py checks what the server receives.
"""

from __future__ import annotations

from dfilterforge.intent_ir import GenerationStatus
from dfilterforge.intent_ir import MissingSlot
from dfilterforge.intent_ir import Operator

TYPED_IR_V1 = "typed-ir/1"
# The name vLLM requires beside a schema; it is not shown to the model.
_SCHEMA_NAME = "generation_result"

# intent_ir.FIELD_NAME_PATTERN, anchored and without a non-capturing group.
_FIELD_PATTERN = r"^[A-Za-z0-9_]+([.-][A-Za-z0-9_]+)*$"
_OCTET = r"(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])"
_IPV4 = rf"{_OCTET}\.{_OCTET}\.{_OCTET}\.{_OCTET}"
# ipaddress reads a prefix length with int(), so leading zeros pass.
_IPV4_SUFFIX = rf"/(0*([0-9]|[12][0-9]|3[0-2])|{_IPV4})"
# Loose on purpose: any run of hex digits, colons and dots holding a colon.
_IPV6 = r"[0-9A-Fa-f:.]*:[0-9A-Fa-f:.]*(%[0-9A-Za-z_.-]+)?"
_IPV6_SUFFIX = r"/0*([0-9]|[1-9][0-9]|1[01][0-9]|12[0-8])"
_SUBNET_PATTERN = rf"^({_IPV4}({_IPV4_SUFFIX})?|{_IPV6}({_IPV6_SUFFIX})?)$"
_COMPARISONS = (
    Operator.EQ,
    Operator.NE,
    Operator.LT,
    Operator.LE,
    Operator.GT,
    Operator.GE,
)
_NODES = (
    "exists",
    "compare",
    "contains",
    "in",
    "in_subnet",
    "all",
    "any",
    "not",
)


def _object(
    properties: dict[str, object], required: tuple[str, ...]
) -> dict[str, object]:
    """Returns a closed object schema with properties in declared order."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _scalar() -> dict[str, object]:
    """Returns the schema of one scalar value: bool, number or string."""
    return {
        "anyOf": [{"type": "boolean"}, {"type": "number"}, {"type": "string"}]
    }


def _predicate(
    operator: dict[str, object], value: dict[str, object] | None
) -> dict[str, object]:
    """Returns one predicate form; ``value`` None marks exists.

    exists may write its value as null or leave it out; every other
    operator must write one.
    """
    properties: dict[str, object] = {
        "kind": {"const": "predicate"},
        "field": {"type": "string", "pattern": _FIELD_PATTERN},
        "operator": operator,
    }
    if value is None:
        properties["value"] = {"type": "null"}
        return _object(properties, ("kind", "field", "operator"))
    properties["value"] = value
    return _object(properties, ("kind", "field", "operator", "value"))


def _junction(kind: str) -> dict[str, object]:
    """Returns an all or any node: two or more children."""
    return _object(
        {
            "kind": {"const": kind},
            "children": {
                "type": "array",
                "items": {"$ref": "#/$defs/node"},
                "minItems": 2,
            },
        },
        ("kind", "children"),
    )


def _definitions() -> dict[str, object]:
    """Returns the recursive node grammar and the Intent IR root."""
    return {
        "exists": _predicate({"const": Operator.EXISTS.value}, None),
        "compare": _predicate(
            {"enum": [operator.value for operator in _COMPARISONS]}, _scalar()
        ),
        "contains": _predicate(
            {"const": Operator.CONTAINS.value}, {"type": "string"}
        ),
        "in": _predicate(
            {"const": Operator.IN.value},
            {"type": "array", "items": _scalar(), "minItems": 1},
        ),
        "in_subnet": _predicate(
            {"const": Operator.IN_SUBNET.value},
            {"type": "string", "pattern": _SUBNET_PATTERN},
        ),
        "all": _junction("all"),
        "any": _junction("any"),
        "not": _object(
            {"kind": {"const": "not"}, "child": {"$ref": "#/$defs/node"}},
            ("kind", "child"),
        ),
        "node": {"anyOf": [{"$ref": f"#/$defs/{name}"} for name in _NODES]},
        "intent_ir": _object(
            {
                "ir_schema_version": {"const": "1.0"},
                "scope": {"const": "packet"},
                "expression": {"$ref": "#/$defs/node"},
            },
            ("expression",),
        ),
    }


def _envelope(
    status: GenerationStatus,
    *,
    question: dict[str, object],
    max_slots: int,
    intent_ir: dict[str, object],
    required: tuple[str, ...],
) -> dict[str, object]:
    """Returns the envelope one status allows, keys in prompt order."""
    return _object(
        {
            "schema_version": {"const": "1.0"},
            "status": {"const": status.value},
            "assumptions": {"type": "array", "items": {"type": "string"}},
            "clarifying_question": question,
            "missing_slots": {
                "type": "array",
                "items": {"enum": [slot.value for slot in MissingSlot]},
                "maxItems": max_slots,
            },
            "intent_ir": intent_ir,
        },
        ("status", *required),
    )


def typed_ir_schema() -> dict[str, object]:
    """Returns the schema of a typed-IR answer, the C3 and C4 envelope.

    A ready answer carries an Intent IR and no question; a
    needs_clarification answer carries a question and no IR;
    a not_expressible answer carries neither. Only needs_clarification
    may name missing slots.
    """
    null: dict[str, object] = {"type": "null"}
    return {
        "anyOf": [
            _envelope(
                GenerationStatus.READY,
                question=null,
                max_slots=0,
                intent_ir={"$ref": "#/$defs/intent_ir"},
                required=("intent_ir",),
            ),
            _envelope(
                GenerationStatus.NEEDS_CLARIFICATION,
                question={"type": "string"},
                max_slots=len(MissingSlot),
                intent_ir=null,
                required=("clarifying_question",),
            ),
            _envelope(
                GenerationStatus.NOT_EXPRESSIBLE,
                question=null,
                max_slots=0,
                intent_ir=null,
                required=(),
            ),
        ],
        "$defs": _definitions(),
    }


_SCHEMAS = {TYPED_IR_V1: typed_ir_schema}


def response_format(name: str) -> dict[str, object]:
    """Returns the ``response_format`` that sends one named schema.

    Args:
        name: A schema version, such as ``typed-ir/1``.

    Raises:
        KeyError: If no schema has that name.
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": _SCHEMA_NAME,
            "schema": _SCHEMAS[name](),
            "strict": True,
        },
    }


def schema_names() -> tuple[str, ...]:
    """Returns every schema version a request may name."""
    return tuple(_SCHEMAS)
