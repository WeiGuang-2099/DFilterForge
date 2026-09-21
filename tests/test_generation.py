"""Behavioral tests for the four-condition prompt and response contracts."""

import json

from pydantic import ValidationError
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
from dfilterforge.intent_ir import MissingSlot

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
_DISPLAY_OK = (
    '{"schema_version":"direct-filter/1.0","status":"ready",'
    '"display_filter":"tcp.dstport == 443"}'
)
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
    '{"schema_version":"direct-filter/1.0","status":"ready",'
    '"display_filter":"tcp","x":1}',
    '{"schema_version":"direct-filter/2.0","status":"ready",'
    '"display_filter":"tcp"}',
    "[" * 5000,
    '{"schema_version":"direct-filter/1.0","status":"ready",'
    '"display_filter":"' + "a" * MAX_RESPONSE_BYTES + '"}',
)
_STATUS_ROWS = (
    ("ready", True, None, True),
    ("ready", False, None, False),
    ("ready", True, "Which port?", False),
    ("needs_clarification", False, "Which port?", True),
    ("needs_clarification", False, None, False),
    ("needs_clarification", True, "Which port?", False),
    ("not_expressible", False, None, True),
    ("not_expressible", True, None, False),
    ("not_expressible", False, "Which port?", False),
)


def _fields_for(
    retrieval: RetrievalV1,
) -> tuple[RetrievedFieldV1, ...] | None:
    return _FIELDS if retrieval is RetrievalV1.LEXICAL else None


def _item(
    item_id: str = "item-1",
    *,
    retrieved_fields: tuple[RetrievedFieldV1, ...] | None = None,
    intent: str = "Show TCP SYN packets sent to port 443",
) -> GenerationInputV1:
    return GenerationInputV1(
        item_id=item_id,
        intent=intent,
        user_assumptions=("Packet scope.",),
        retrieved_fields=retrieved_fields,
        split="dev",
    )


def _status_envelope(
    output_contract: OutputContractV1,
    status: str,
    payload: bool,
    question: str | None,
    slots: tuple[str, ...] = (),
) -> str:
    typed = output_contract is OutputContractV1.TYPED_IR
    key = "intent_ir" if typed else "display_filter"
    value: object = _READY_IR if typed else "tcp.dstport == 443"
    return json.dumps(
        {
            "schema_version": "1.0" if typed else "direct-filter/1.0",
            "status": status,
            "assumptions": [],
            "clarifying_question": question,
            "missing_slots": list(slots),
            key: value if payload else None,
        }
    )


def _batch(
    output_contract: OutputContractV1,
    retrieval: RetrievalV1,
    *items: GenerationInputV1,
) -> PreparedBatchV1:
    return prepare_batch(
        items or (_item(retrieved_fields=_fields_for(retrieval)),),
        output_contract=output_contract,
        retrieval=retrieval,
    )


def _system(output_contract: OutputContractV1, retrieval: RetrievalV1) -> str:
    return _batch(output_contract, retrieval).prompts[0].messages[0].content


def _rule_line(system: str) -> str:
    (line,) = [
        text
        for text in system.splitlines()
        if text.startswith("status is ready, needs_clarification,")
    ]
    return line


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
        _item("first", retrieved_fields=_fields_for(retrieval)),
        _item(
            "second",
            retrieved_fields=_fields_for(retrieval),
            intent="Show DNS responses",
        ),
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
        _item("a", retrieved_fields=_FIELDS),
        _item("b", retrieved_fields=_FIELDS, intent="Match DNS"),
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
    ("retrieval", "retrieved_fields", "code"),
    [
        (RetrievalV1.LEXICAL, None, "retrieval_required"),
        (RetrievalV1.NONE, (), "retrieval_forbidden"),
        (RetrievalV1.NONE, _FIELDS, "retrieval_forbidden"),
    ],
)
def test_retrieval_treatment_must_match_the_supplied_context(
    output_contract: OutputContractV1,
    retrieval: RetrievalV1,
    retrieved_fields: tuple[RetrievedFieldV1, ...] | None,
    code: str,
) -> None:
    with pytest.raises(GenerationError) as caught:
        _batch(
            output_contract,
            retrieval,
            _item(retrieved_fields=retrieved_fields),
        )

    assert caught.value.code == code


@pytest.mark.parametrize(
    "output_contract",
    [OutputContractV1.DISPLAY_FILTER, OutputContractV1.TYPED_IR],
)
def test_lexical_prompt_may_carry_an_empty_field_list(
    output_contract: OutputContractV1,
) -> None:
    batch = _batch(
        output_contract, RetrievalV1.LEXICAL, _item(retrieved_fields=())
    )

    prompt = batch.prompts[0]
    system = prompt.messages[0].content
    assert _user_payload(prompt)["retrieved_fields"] == []
    assert prompt.retrieved_fields == ()
    assert "use only those field names" in system
    assert "use standard Wireshark field names" in system
    assert PreparedBatchV1.model_validate_json(batch.model_dump_json()) == batch
    document = prompt.model_dump(mode="json")
    payload = _user_payload(prompt)
    del payload["retrieved_fields"]
    document["messages"][1]["content"] = "INPUT_JSON\n" + json.dumps(payload)
    with pytest.raises(ValueError, match="differ from prompt field context"):
        PreparedPromptV1.model_validate(document)


def test_system_prompts_state_identical_abstention_rules() -> None:
    direct = _system(OutputContractV1.DISPLAY_FILTER, RetrievalV1.LEXICAL)
    typed = _system(OutputContractV1.TYPED_IR, RetrievalV1.LEXICAL)
    clause = direct.splitlines()[-1]

    # The two contracts must state one rule set, differing only in the name
    # of the payload each of them carries.
    assert _rule_line(direct).replace("display_filter", "intent_ir") == (
        _rule_line(typed)
    )
    for system in (direct, typed):
        assert "missing_slots is [] unless status is needs_clarification" in (
            system
        )
        assert all(slot.value in system for slot in MissingSlot)
        assert system.endswith("\n" + clause)
    assert "use only those field names" in clause
    assert (
        "When that list is empty, no catalog field matched; use standard "
        "Wireshark field names." in clause
    )
    assert clause not in _system(
        OutputContractV1.DISPLAY_FILTER, RetrievalV1.NONE
    )


@pytest.mark.parametrize(
    "output_contract",
    [OutputContractV1.DISPLAY_FILTER, OutputContractV1.TYPED_IR],
)
@pytest.mark.parametrize(
    ("status", "payload", "question", "accepted"), _STATUS_ROWS
)
def test_both_contracts_share_one_status_channel(
    output_contract: OutputContractV1,
    status: str,
    payload: bool,
    question: str | None,
    accepted: bool,
) -> None:
    text = _status_envelope(output_contract, status, payload, question)
    ready_with_slots = _status_envelope(
        output_contract, "ready", True, None, ("port",)
    )

    if accepted:
        result = parse_response(output_contract, text)
        assert result.status == GenerationStatus(status)
        assert result.clarifying_question == question
        assert result.missing_slots == ()
    else:
        with pytest.raises(GenerationError) as caught:
            parse_response(output_contract, text)
        assert caught.value.code == "response_invalid"
    with pytest.raises(GenerationError) as slotted:
        parse_response(output_contract, ready_with_slots)

    assert slotted.value.code == "response_invalid"


def test_retrieved_fields_keep_catalog_text_verbatim() -> None:
    protocol = RetrievedFieldV1(
        rank=1,
        abbreviation="usbdfu",
        field_type=FieldType.PROTOCOL,
        protocol="usbdfu",
        display_name="USB Device Firmware Upgrade ",
    )
    mixed_case = RetrievedFieldV1(
        rank=1,
        abbreviation="bacapp.IPV4",
        field_type=FieldType.IPV4,
        protocol="bacapp",
        display_name="IPV4",
    )

    assert protocol.display_name == "USB Device Firmware Upgrade "
    assert mixed_case.abbreviation == "bacapp.IPV4"
    with pytest.raises(ValidationError):
        RetrievedFieldV1(
            rank=1,
            abbreviation="usbdfu",
            field_type=FieldType.PROTOCOL,
            protocol="usbdfu",
            display_name="   ",
        )
    with pytest.raises(ValidationError):
        RetrievedFieldV1(
            rank=1,
            abbreviation="tcp.",
            field_type=FieldType.PROTOCOL,
            protocol="tcp",
            display_name="Transmission Control Protocol",
        )


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

    assert direct == DirectFilterResultV1(
        status=GenerationStatus.READY, display_filter="tcp.dstport == 443"
    )
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
            "status": "ready",
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
        _item("one", retrieved_fields=_FIELDS, intent="Show TCP SYN"),
        _item("two", retrieved_fields=_FIELDS, intent="Show DNS queries"),
        _item("three", retrieved_fields=_FIELDS, intent="Show port 443"),
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

    direct = parse_response(
        OutputContractV1.DISPLAY_FILTER,
        json.dumps(
            {
                "schema_version": "direct-filter/1.0",
                "status": "needs_clarification",
                "assumptions": [],
                "clarifying_question": "Can you clarify what you want?",
                "missing_slots": [],
                "display_filter": None,
            }
        ),
    )

    assert isinstance(direct, DirectFilterResultV1)
    assert direct.status is GenerationStatus.NEEDS_CLARIFICATION
    assert direct.display_filter is None
