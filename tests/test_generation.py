"""Behavioral tests for the four-condition prompt and response contracts."""

import json

import pytest

from dfilterforge.errors import DFilterForgeError
from dfilterforge.field_catalog import FieldType
from dfilterforge.generation import condition_label
from dfilterforge.generation import DirectFilterResultV1
from dfilterforge.generation import GenerationError
from dfilterforge.generation import GenerationInputV1
from dfilterforge.generation import MAX_RESPONSE_BYTES
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import parse_response
from dfilterforge.generation import prepare_batch
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import PreparedPromptV1
from dfilterforge.generation import RetrievalV1
from dfilterforge.generation import RetrievedFieldV1
from dfilterforge.intent_ir import GenerationResultV1
from dfilterforge.intent_ir import GenerationStatus

_CONDITIONS = (
    (OutputContractV1.DISPLAY_FILTER, RetrievalV1.NONE, "C1"),
    (OutputContractV1.DISPLAY_FILTER, RetrievalV1.LEXICAL, "C2"),
    (OutputContractV1.TYPED_IR, RetrievalV1.NONE, "C3"),
    (OutputContractV1.TYPED_IR, RetrievalV1.LEXICAL, "C4"),
)
_FIELDS = (
    RetrievedFieldV1(
        rank=1,
        abbreviation="tcp.dstport",
        field_type=FieldType.INTEGER,
        protocol="tcp",
        display_name="Destination Port",
    ),
    RetrievedFieldV1(
        rank=2,
        abbreviation="tcp.flags.syn",
        field_type=FieldType.BOOLEAN,
        protocol="tcp",
        display_name="Syn",
        enum_values=("Set", "Not set"),
    ),
)
_READY_IR = {
    "ir_schema_version": "1.0",
    "scope": "packet",
    "expression": {
        "kind": "predicate",
        "field": "tcp.dstport",
        "operator": "eq",
        "value": 443,
    },
}
_DISPLAY_OK = '{"schema_version":"direct-filter/1.0","display_filter":"tcp.dstport == 443"}'
_TYPED_OK = json.dumps(
    {
        "schema_version": "1.0",
        "status": "ready",
        "assumptions": ["Packet scope."],
        "clarifying_question": None,
        "intent_ir": _READY_IR,
    }
)
_MALFORMED = (
    "",
    "tcp.dstport == 443",
    "```json\n" + _DISPLAY_OK + "\n```",
    "Here is the JSON you asked for: " + _DISPLAY_OK,
    _DISPLAY_OK + "\nLet me know if you need anything else.",
    _TYPED_OK + " trailing",
    "[]",
    "null",
    "{}",
    '{"schema_version":"direct-filter/1.0","display_filter":"tcp","x":1}',
    '{"schema_version":"direct-filter/2.0","display_filter":"tcp"}',
    "[" * 5000,
    '{"schema_version":"direct-filter/1.0","display_filter":"'
    + "a" * MAX_RESPONSE_BYTES
    + '"}',
)


def _item(
    item_id: str = "item-1",
    *,
    retrieval: RetrievalV1 = RetrievalV1.NONE,
    intent: str = "Show TCP SYN packets sent to port 443",
) -> GenerationInputV1:
    return GenerationInputV1(
        item_id=item_id,
        intent=intent,
        user_assumptions=("Packet scope.",),
        retrieved_fields=_FIELDS if retrieval is RetrievalV1.LEXICAL else (),
        split="dev",
    )


def _batch(
    output_contract: OutputContractV1,
    retrieval: RetrievalV1,
    *items: GenerationInputV1,
) -> PreparedBatchV1:
    return prepare_batch(
        items or (_item(retrieval=retrieval),),
        output_contract=output_contract,
        retrieval=retrieval,
    )


def _user_payload(prompt: PreparedPromptV1) -> dict[str, object]:
    content = prompt.messages[1].content
    assert content.startswith("INPUT_JSON\n")
    return json.loads(content.removeprefix("INPUT_JSON\n"))


@pytest.mark.parametrize(("output_contract", "retrieval", "label"), _CONDITIONS)
def test_each_condition_prepares_prompts_with_fields_only_under_lexical(
    output_contract: OutputContractV1, retrieval: RetrievalV1, label: str
) -> None:
    batch = _batch(output_contract, retrieval)

    assert condition_label(output_contract, retrieval) == label
    assert (batch.output_contract, batch.retrieval) == (
        output_contract,
        retrieval,
    )
    prompt = batch.prompts[0]
    assert (prompt.output_contract, prompt.retrieval) == (
        output_contract,
        retrieval,
    )
    assert prompt.item_id == "item-1"
    assert prompt.split == "dev"
    system, user = (message.content for message in prompt.messages)
    lexical = retrieval is RetrievalV1.LEXICAL
    payload = _user_payload(prompt)
    expected_keys = {"intent", "user_assumptions"}
    if lexical:
        expected_keys.add("retrieved_fields")
        assert payload["retrieved_fields"] == json.loads(
            json.dumps([field.model_dump(mode="json") for field in _FIELDS])
        )
        assert prompt.retrieved_fields == _FIELDS
    else:
        assert "tcp.dstport" not in user
        assert prompt.retrieved_fields == ()
    assert set(payload) == expected_keys
    assert ("retrieved_fields" in system) is lexical
    typed = output_contract is OutputContractV1.TYPED_IR
    assert ("generation-result/1.0" in system) is typed
    assert ("direct-filter/1.0" in system) is not typed
    assert "item-1" not in system + user
    assert '"split"' not in user


@pytest.mark.parametrize(("output_contract", "retrieval", "label"), _CONDITIONS)
def test_prepared_batches_round_trip_through_json(
    output_contract: OutputContractV1, retrieval: RetrievalV1, label: str
) -> None:
    batch = _batch(
        output_contract,
        retrieval,
        _item("first", retrieval=retrieval),
        _item("second", retrieval=retrieval, intent="Show DNS responses"),
    )

    encoded = batch.model_dump_json()
    decoded = PreparedBatchV1.model_validate_json(encoded)

    assert decoded == batch
    document = json.loads(encoded)
    assert document["output_contract"] == output_contract.value
    assert document["retrieval"] == retrieval.value
    assert [prompt["item_id"] for prompt in document["prompts"]] == [
        "first",
        "second",
    ]
    assert condition_label(decoded.output_contract, decoded.retrieval) == label


def test_prompt_preparation_is_deterministic() -> None:
    items = (
        _item("a", retrieval=RetrievalV1.LEXICAL),
        _item("b", retrieval=RetrievalV1.LEXICAL, intent="Match DNS"),
    )

    first = _batch(OutputContractV1.TYPED_IR, RetrievalV1.LEXICAL, *items)
    second = _batch(OutputContractV1.TYPED_IR, RetrievalV1.LEXICAL, *items)

    assert first == second
    assert tuple(prompt.item_id for prompt in first.prompts) == ("a", "b")


@pytest.mark.parametrize(
    "output_contract",
    [OutputContractV1.DISPLAY_FILTER, OutputContractV1.TYPED_IR],
)
@pytest.mark.parametrize(
    ("retrieval", "item_retrieval", "code"),
    [
        (RetrievalV1.LEXICAL, RetrievalV1.NONE, "retrieval_required"),
        (RetrievalV1.NONE, RetrievalV1.LEXICAL, "retrieval_forbidden"),
    ],
)
def test_retrieval_treatment_must_match_the_supplied_context(
    output_contract: OutputContractV1,
    retrieval: RetrievalV1,
    item_retrieval: RetrievalV1,
    code: str,
) -> None:
    with pytest.raises(GenerationError) as caught:
        _batch(output_contract, retrieval, _item(retrieval=item_retrieval))

    assert caught.value.code == code


def test_batches_reject_empty_input_and_duplicate_ids() -> None:
    with pytest.raises(GenerationError) as empty:
        prepare_batch(
            (),
            output_contract=OutputContractV1.DISPLAY_FILTER,
            retrieval=RetrievalV1.NONE,
        )
    with pytest.raises(GenerationError) as duplicate:
        _batch(
            OutputContractV1.DISPLAY_FILTER,
            RetrievalV1.NONE,
            _item("same"),
            _item("same", intent="Different words"),
        )

    assert empty.value.code == "batch_empty"
    assert duplicate.value.code == "duplicate_item_id"
    assert isinstance(empty.value, DFilterForgeError)


def test_prompt_byte_budget_is_enforced_before_any_request() -> None:
    oversized = GenerationInputV1(
        item_id="big",
        intent="Show everything",
        user_assumptions=("a" * 4000,) * 20,
    )

    with pytest.raises(GenerationError) as caught:
        _batch(OutputContractV1.DISPLAY_FILTER, RetrievalV1.NONE, oversized)

    assert caught.value.code == "prompt_too_large"


def test_recorded_context_cannot_diverge_from_the_visible_prompt() -> None:
    lexical = _batch(OutputContractV1.DISPLAY_FILTER, RetrievalV1.LEXICAL)
    prompt = lexical.prompts[0].model_dump(mode="json")
    prompt["retrieved_fields"] = prompt["retrieved_fields"][:1]

    with pytest.raises(ValueError, match="differ from prompt field context"):
        PreparedPromptV1.model_validate(prompt)
    with pytest.raises(ValueError, match="does not match the batch"):
        PreparedBatchV1(
            output_contract=OutputContractV1.DISPLAY_FILTER,
            retrieval=RetrievalV1.NONE,
            prompts=lexical.prompts,
        )


@pytest.mark.parametrize(
    "output_contract",
    [OutputContractV1.DISPLAY_FILTER, OutputContractV1.TYPED_IR],
)
@pytest.mark.parametrize(
    "response_text",
    _MALFORMED,
    ids=[f"malformed-{index}" for index in range(len(_MALFORMED))],
)
def test_parse_response_never_repairs_or_extracts(
    output_contract: OutputContractV1, response_text: str
) -> None:
    with pytest.raises(GenerationError) as caught:
        parse_response(output_contract, response_text)

    assert caught.value.code == "response_invalid"


def test_parse_response_accepts_only_its_own_exact_envelope() -> None:
    direct = parse_response(OutputContractV1.DISPLAY_FILTER, _DISPLAY_OK)
    typed = parse_response(OutputContractV1.TYPED_IR, _TYPED_OK)

    assert direct == DirectFilterResultV1(display_filter="tcp.dstport == 443")
    assert isinstance(typed, GenerationResultV1)
    assert typed.status is GenerationStatus.READY
    assert typed.intent_ir is not None
    assert typed.intent_ir.expression.kind == "predicate"
    with pytest.raises(GenerationError):
        parse_response(OutputContractV1.DISPLAY_FILTER, _TYPED_OK)
    with pytest.raises(GenerationError):
        parse_response(OutputContractV1.TYPED_IR, _DISPLAY_OK)


@pytest.mark.parametrize(
    "display_filter", ["", "   ", "tcp\x00secret", "tcp\nsecret", "a" * 4097]
)
def test_display_filter_envelope_rejects_unsafe_filters(
    display_filter: str,
) -> None:
    text = json.dumps(
        {
            "schema_version": "direct-filter/1.0",
            "display_filter": display_filter,
        }
    )

    with pytest.raises(GenerationError) as caught:
        parse_response(OutputContractV1.DISPLAY_FILTER, text)

    assert caught.value.code == "response_invalid"
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    ("status", "intent_ir", "question", "accepted"),
    [
        ("ready", _READY_IR, None, True),
        ("ready", None, None, False),
        ("ready", _READY_IR, "Which port?", False),
        ("needs_clarification", None, "Which port?", True),
        ("needs_clarification", None, None, False),
        ("needs_clarification", _READY_IR, "Which port?", False),
        ("not_expressible", None, None, True),
        ("not_expressible", _READY_IR, None, False),
        ("not_expressible", None, "Which port?", False),
    ],
)
def test_generation_status_payload_rules_hold_through_strict_parsing(
    status: str,
    intent_ir: dict[str, object] | None,
    question: str | None,
    accepted: bool,
) -> None:
    text = json.dumps(
        {
            "schema_version": "1.0",
            "status": status,
            "assumptions": [],
            "clarifying_question": question,
            "intent_ir": intent_ir,
        }
    )

    if accepted:
        result = parse_response(OutputContractV1.TYPED_IR, text)
        assert isinstance(result, GenerationResultV1)
        assert result.status == GenerationStatus(status)
        assert (result.intent_ir is not None) is (intent_ir is not None)
        assert result.clarifying_question == question
    else:
        with pytest.raises(GenerationError) as caught:
            parse_response(OutputContractV1.TYPED_IR, text)
        assert caught.value.code == "response_invalid"


def test_blanket_clarification_is_representable_but_never_ready() -> None:
    batch = _batch(
        OutputContractV1.TYPED_IR,
        RetrievalV1.LEXICAL,
        _item("one", retrieval=RetrievalV1.LEXICAL, intent="Show TCP SYN"),
        _item("two", retrieval=RetrievalV1.LEXICAL, intent="Show DNS queries"),
        _item("three", retrieval=RetrievalV1.LEXICAL, intent="Show port 443"),
    )
    blanket = json.dumps(
        {
            "schema_version": "1.0",
            "status": "needs_clarification",
            "assumptions": [],
            "clarifying_question": "Can you clarify what you want?",
            "intent_ir": None,
        }
    )

    results = [
        parse_response(prompt.output_contract, blanket)
        for prompt in batch.prompts
    ]

    # The status is the flag a scorer keys on: none of these count as ready
    # and none carries an intent_ir that could be compiled or credited.
    typed = [
        result for result in results if isinstance(result, GenerationResultV1)
    ]
    assert len(typed) == 3
    assert {result.status for result in typed} == {
        GenerationStatus.NEEDS_CLARIFICATION
    }
    assert all(result.intent_ir is None for result in typed)
