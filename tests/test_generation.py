"""Behavioral tests for the four-condition prompt and response contracts."""

import hashlib
import json
from pathlib import Path
from typing import cast

from pydantic import ValidationError
import pytest

from dfilterforge.canonical import canonical_json
from dfilterforge.errors import DFilterForgeError
from dfilterforge.field_catalog import FieldType
from dfilterforge.generation import condition_label
from dfilterforge.generation import COUNTEREXAMPLE_PREFIX
from dfilterforge.generation import DirectFilterResultV1
from dfilterforge.generation import follow_up_prompt
from dfilterforge.generation import FOLLOW_UP_TEXT
from dfilterforge.generation import GenerationError
from dfilterforge.generation import GenerationInputV1
from dfilterforge.generation import MAX_CARD_BYTES
from dfilterforge.generation import MAX_PROMPT_BYTES
from dfilterforge.generation import MAX_RESPONSE_BYTES
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import parse_response
from dfilterforge.generation import prepare_batch
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import PreparedPromptV1
from dfilterforge.generation import prompt_versions
from dfilterforge.generation import RetrievalV1
from dfilterforge.generation import RetrievedFieldV1
from dfilterforge.intent_ir import GenerationResultV1
from dfilterforge.intent_ir import GenerationStatus
from dfilterforge.intent_ir import MissingSlot
from dfilterforge.repair import PLAN_PATH
from dfilterforge.repair_round import arm_run_ids
from dfilterforge.repair_summary import ARMS

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


# The system prompts committed runs were prepared with, by version. A run
# re-scores only while its version still rebuilds these exact bytes.
_COMMITTED_SYSTEMS = {
    (OutputContractV1.DISPLAY_FILTER, RetrievalV1.NONE, 1): (
        "ab9b4bd96df39af5e7d14ea1dbcc7bb6003a9fa41ae974ff7a790242c355eb38"
    ),
    (OutputContractV1.DISPLAY_FILTER, RetrievalV1.LEXICAL, 1): (
        "81b43bf2b04167d858e484a2f9d8f2ea5f5eeae0f7938723cfc39007c5a9af2a"
    ),
    (OutputContractV1.TYPED_IR, RetrievalV1.NONE, 1): (
        "8980a4eaba1f0d8014f80e46982075baad859609ca817a37be77f3f2b4482c6e"
    ),
    (OutputContractV1.TYPED_IR, RetrievalV1.LEXICAL, 1): (
        "fdeb379cc080c8ba14a1fdecf758fe7ed2e1cc8bcafc5f9b150e0b8fdda37414"
    ),
    (OutputContractV1.TYPED_IR, RetrievalV1.NONE, 2): (
        "19f2e94c060146fe9f5f8c5c51cd7e49d33571bdc92605545738e97d91603e61"
    ),
    (OutputContractV1.TYPED_IR, RetrievalV1.LEXICAL, 2): (
        "35f4275d08a8150e750eb73a64334444db14caffd5168760a0fdbb4baaa1626a"
    ),
}


@pytest.mark.parametrize(
    ("output_contract", "retrieval", "version"), list(_COMMITTED_SYSTEMS)
)
def test_committed_prompt_versions_rebuild_byte_for_byte(
    output_contract: OutputContractV1, retrieval: RetrievalV1, version: int
) -> None:
    batch = prepare_batch(
        (_item(retrieved_fields=_fields_for(retrieval)),),
        output_contract=output_contract,
        retrieval=retrieval,
        prompt_version=version,
    )
    system = batch.prompts[0].messages[0].content

    assert hashlib.sha256(system.encode("utf-8")).hexdigest() == (
        _COMMITTED_SYSTEMS[(output_contract, retrieval, version)]
    )


def test_new_batches_use_the_latest_prompt_version() -> None:
    latest = prompt_versions(OutputContractV1.TYPED_IR)
    first = prepare_batch(
        (_item(),),
        output_contract=OutputContractV1.TYPED_IR,
        retrieval=RetrievalV1.NONE,
        prompt_version=1,
    )

    assert latest == 2
    assert prompt_versions(OutputContractV1.DISPLAY_FILTER) == 1
    assert _system(OutputContractV1.TYPED_IR, RetrievalV1.NONE) != (
        first.prompts[0].messages[0].content
    )
    for version in (0, latest + 1):
        with pytest.raises(GenerationError, match="no prompt version"):
            prepare_batch(
                (_item(),),
                output_contract=OutputContractV1.TYPED_IR,
                retrieval=RetrievalV1.NONE,
                prompt_version=version,
            )


def test_typed_prompt_states_how_every_bound_type_is_written() -> None:
    system = _system(OutputContractV1.TYPED_IR, RetrievalV1.NONE)
    typed = " ".join(system.split())
    direct = _system(OutputContractV1.DISPLAY_FILTER, RetrievalV1.NONE)

    # The binder rejects a value whose JSON type does not match its field,
    # so a contract without retrieved field types must still say how each
    # type the catalog binds is written, and how a group is nested.
    for field_type in FieldType:
        if field_type is not FieldType.UNSUPPORTED:
            assert field_type.value in typed
    assert "never a quoted one" in typed
    assert "true or false for boolean fields" in typed
    assert "take two or more children" in typed
    assert "JSON number" not in direct


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


# The registered second user turn of the two-turn smoke, by digest, so a
# wording change is visible here before any request carries it.
_FOLLOW_UP_SHA256 = (
    "d903bc2e346b20aca5625f97134312ccb51dbabb3c6392623325e4f2a9394d62"
)
_RESULTS = Path(__file__).parents[1] / "docs" / "results"


def _first_turn() -> PreparedPromptV1:
    return _batch(OutputContractV1.TYPED_IR, RetrievalV1.LEXICAL).prompts[0]


def _with_roles(*roles: str) -> dict[str, object]:
    """A first-turn prompt document whose messages carry these roles."""
    document = _first_turn().model_dump(mode="json")
    first = cast(list[dict[str, str]], document["messages"])
    contents = (first[0]["content"], first[1]["content"], "{}", "Again.")
    document["messages"] = [
        {"role": role, "content": contents[min(index, 3)]}
        for index, role in enumerate(roles)
    ]
    return document


def test_follow_up_text_is_pinned() -> None:
    encoded = FOLLOW_UP_TEXT.encode("utf-8")

    assert FOLLOW_UP_TEXT == (
        "Your filter was incorrect. Reply with a corrected answer in the "
        "same JSON format."
    )
    assert hashlib.sha256(encoded).hexdigest() == _FOLLOW_UP_SHA256
    assert len(encoded) == 81


def test_follow_up_prompt_continues_with_the_answer_verbatim() -> None:
    prompt = _first_turn()
    answer = ' {"status": "ready"}\né'

    continued = follow_up_prompt(prompt, answer)

    assert [message.role for message in continued.messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert continued.messages[:2] == prompt.messages
    assert continued.messages[2].content.encode("utf-8") == answer.encode(
        "utf-8"
    )
    assert continued.messages[3].content == FOLLOW_UP_TEXT
    assert continued.model_dump(exclude={"messages"}) == prompt.model_dump(
        exclude={"messages"}
    )
    batch = PreparedBatchV1(
        output_contract=prompt.output_contract,
        retrieval=prompt.retrieval,
        prompts=(continued,),
    )
    assert PreparedBatchV1.model_validate_json(canonical_json(batch)) == batch


@pytest.mark.parametrize(
    "roles",
    [
        ("user", "system"),
        ("system",),
        ("system", "user", "assistant"),
        ("system", "user", "user", "assistant"),
        ("system", "assistant", "user", "user"),
        ("system", "user", "system", "user"),
        ("system", "user", "assistant", "assistant"),
        ("system", "user", "assistant", "user", "assistant", "user"),
    ],
)
def test_prepared_prompts_accept_only_the_two_message_shapes(
    roles: tuple[str, ...],
) -> None:
    for accepted in (
        ("system", "user"),
        ("system", "user", "assistant", "user"),
    ):
        PreparedPromptV1.model_validate(_with_roles(*accepted))

    with pytest.raises(ValidationError):
        PreparedPromptV1.model_validate(_with_roles(*roles))


def test_a_second_turn_counts_every_message_toward_the_byte_budget() -> None:
    document = _with_roles("system", "user", "assistant", "user")
    messages = cast(list[dict[str, str]], document["messages"])
    used = sum(len(m["content"].encode("utf-8")) for m in messages[:2])
    messages[2]["content"] = "x" * (MAX_PROMPT_BYTES - used - 5)
    messages[3]["content"] = "12345"
    PreparedPromptV1.model_validate(document)

    messages[3]["content"] = "123456"
    with pytest.raises(ValidationError, match="prompt exceeds the byte limit"):
        PreparedPromptV1.model_validate(document)


def test_follow_up_prompt_refusals() -> None:
    prompt = _first_turn()
    used = sum(len(m.content.encode("utf-8")) for m in prompt.messages)
    room = MAX_PROMPT_BYTES - used - len(FOLLOW_UP_TEXT.encode("utf-8"))
    continued = follow_up_prompt(prompt, "x" * room)
    assert len(continued.messages) == 4

    cases = (
        (continued, "{}", "follow_up_invalid"),
        (prompt, "", "follow_up_invalid"),
        (prompt, "\ud800", "follow_up_invalid"),
        (prompt, "x" * (room + 1), "prompt_too_large"),
    )
    for base, answer, code in cases:
        with pytest.raises(GenerationError) as caught:
            follow_up_prompt(base, answer)
        assert caught.value.code == code


# The line a counterexample card follows, by digest, for the same reason.
_COUNTEREXAMPLE_PREFIX_SHA256 = (
    "5918ae3ab3515d45e8404c64db31ebc320d1f04426912762fa3893abca05327e"
)
# A frames card and an error card in the repair round's two shapes.
_FRAMES_CARD = canonical_json(
    {
        "frames": [
            {
                "answer_matched": True,
                "dns.flags.response": False,
                "dns.qry.type": 1,
                "frame": 1,
                "ip.dsfield.ecn": 0,
                "ip.dst": "198.51.100.1",
                "ip.src": "192.0.2.129",
                "ip.ttl": 64,
                "should_match": False,
                "udp.dstport": 53,
                "udp.srcport": 41129,
            },
            {
                "answer_matched": False,
                "frame": 4,
                "ip.dst": "192.0.2.10",
                "ip.src": "198.51.100.7",
                "should_match": True,
                "tcp.dstport": 443,
                "tcp.flags": ["SYN", "ACK"],
                "tcp.len": 0,
                "tcp.srcport": 41000,
            },
        ]
    }
)
_ERROR_CARD = '{"error":"unknown_field","field":"dns.qry.nmae"}'
# The nine two-turn smoke prompt sets prepared on 2026-09-26, by the C4
# digest the smoke's plan.json records for each. The fixture holds their
# three shared first turns and each smoke's two counted answers, copied from
# artifacts/two-turn-smoke of the repair-multiturn worktree at 281b2ce.
_SMOKE_C4_SHA256 = {
    "dev-deepseek-v4-pro-0813-rs-2026-09-26": (
        "3386b2e9dbfef44db55cd624b82f6d91e2c929821d1a38466cad6b763c082a13"
    ),
    "dev-glm-5.2-rs-2026-09-26": (
        "3252677de24888940b5b0c19d2b89e84d3ea871d6cd1dbdaa189943b28b7786a"
    ),
    "dev-granite-4.2-8b-rs-2026-09-26": (
        "d956075a70dfebd735443db4ba4174a8a9d98509767d02c301cd317c7f73138a"
    ),
    "dev-kimi-k2.6-rs-2026-09-26": (
        "fae8f06f3d54fadbae3c9e0fcbdbe87fd5552be1e77392a9aeb7f7277e38c06c"
    ),
    "dev-ministral-8b-2512-rs-2026-09-26": (
        "5d3103328b975671cd5355fb5dd60dd984e277d6c0b2e8669db15c74ca5005f1"
    ),
    "dev-nemotron-3-super-120b-a12b-rs-2026-09-26": (
        "ebe5166fd3718b4c2d1a43d4520dec2a7140ccddfa88d8b9e6ff3cd58b9967ca"
    ),
    "dev-qwen3-32b-rs-2026-09-26": (
        "ef4a27641c0ab6ba0bdeb2d0e6e8ccc6b248ebf086ea63bf80387a9f3f22c7b1"
    ),
    "dev-qwen3.5-122b-a10b-rs-2026-09-26": (
        "ef4a27641c0ab6ba0bdeb2d0e6e8ccc6b248ebf086ea63bf80387a9f3f22c7b1"
    ),
    "dev-qwen3.5-9b-rs-2026-09-26": (
        "87c7d3a2484f07d354577fee34c0ff806ff93b08ee81f8a1de98bb45ae839e2a"
    ),
}
_SMOKE_FIXTURE = Path(__file__).parent / "data" / "smoke_second_turns.json"


def _object_of(size: int, filler: str = "a") -> str:
    """A canonical one-key JSON object of exactly ``size`` UTF-8 bytes.

    The string value is ``filler`` repeated, padded with ``a`` to reach the
    size, so a multi-byte filler gives fewer characters than bytes.
    """
    room = size - len('{"k":""}')
    width = len(filler.encode("utf-8"))
    text = filler * (room // width) + "a" * (room % width)
    card = canonical_json({"k": text})
    assert len(card.encode("utf-8")) == size
    return card


def test_counterexample_prefix_is_pinned() -> None:
    encoded = COUNTEREXAMPLE_PREFIX.encode("utf-8")

    assert COUNTEREXAMPLE_PREFIX == "\nCOUNTEREXAMPLE_JSON\n"
    assert hashlib.sha256(encoded).hexdigest() == (
        _COUNTEREXAMPLE_PREFIX_SHA256
    )
    assert len(encoded) == 21
    assert MAX_CARD_BYTES == 1024


def test_the_nine_smoke_prompt_sets_rebuild_byte_for_byte() -> None:
    """Without a card, a second turn is the one the smoke prepared.

    Each set is rebuilt from its first turns and counted answers, with the
    card left out and passed as ``None``, and must hash to the digest the
    smoke recorded, so the card moved no byte of a prompt set prepared
    before it.
    """
    fixture = json.loads(_SMOKE_FIXTURE.read_text(encoding="utf-8"))
    first_turns = {
        prompt.item_id: prompt
        for prompt in map(
            PreparedPromptV1.model_validate,
            cast(list[object], fixture["first_turns"]),
        )
    }
    smokes = cast(list[dict[str, object]], fixture["smokes"])
    digests: dict[str, str] = {}

    for smoke in smokes:
        prompts: list[PreparedPromptV1] = []
        for entry in cast(list[dict[str, str]], smoke["answers"]):
            first = first_turns[entry["item_id"]]
            default = follow_up_prompt(first, entry["answer"])
            assert follow_up_prompt(first, entry["answer"], None) == default
            prompts.append(default)
        batch = PreparedBatchV1(
            output_contract=OutputContractV1.TYPED_IR,
            retrieval=RetrievalV1.LEXICAL,
            prompts=tuple(prompts),
        )
        data = (canonical_json(batch) + "\n").encode("utf-8")
        reread = PreparedBatchV1.model_validate_json(data)
        assert (canonical_json(reread) + "\n").encode("utf-8") == data
        smoke_id = cast(str, smoke["smoke_id"])
        digests[smoke_id] = hashlib.sha256(data).hexdigest()

    assert len(smokes) == 9
    assert digests == _SMOKE_C4_SHA256


@pytest.mark.parametrize("card", [_FRAMES_CARD, _ERROR_CARD])
def test_a_card_follows_the_follow_up_on_its_own_line(card: str) -> None:
    prompt = _first_turn()
    answer = ' {"status": "ready"}\né'

    bare = follow_up_prompt(prompt, answer)
    continued = follow_up_prompt(prompt, answer, card)

    assert continued.messages[:3] == bare.messages[:3]
    assert continued.messages[3].role == "user"
    assert continued.messages[3].content == (
        FOLLOW_UP_TEXT + COUNTEREXAMPLE_PREFIX + card
    )
    assert continued.messages[3].content.split("\n") == [
        FOLLOW_UP_TEXT,
        "COUNTEREXAMPLE_JSON",
        card,
    ]
    assert continued.model_dump(exclude={"messages"}) == bare.model_dump(
        exclude={"messages"}
    )
    batch = PreparedBatchV1(
        output_contract=prompt.output_contract,
        retrieval=prompt.retrieval,
        prompts=(continued,),
    )
    assert PreparedBatchV1.model_validate_json(canonical_json(batch)) == batch


def test_a_card_may_take_its_whole_byte_limit() -> None:
    card = _object_of(MAX_CARD_BYTES)

    continued = follow_up_prompt(_first_turn(), "{}", card)

    assert continued.messages[3].content.endswith(COUNTEREXAMPLE_PREFIX + card)


@pytest.mark.parametrize(
    "card",
    [
        pytest.param("", id="empty"),
        pytest.param(" " + _ERROR_CARD, id="leading-space"),
        pytest.param(_ERROR_CARD + "\n", id="trailing-newline"),
        pytest.param(
            '{"field":"dns.qry.nmae","error":"unknown_field"}',
            id="unsorted-keys",
        ),
        pytest.param('{"error": "unknown_field"}', id="whitespace"),
        pytest.param(
            '{"error":"unknown_field","error":"unknown_field"}',
            id="repeated-key",
        ),
        pytest.param('{"error":"\\u0075nknown_field"}', id="needless-escape"),
        pytest.param('{"error":NaN}', id="not-a-number"),
        pytest.param("[" + _ERROR_CARD + "]", id="array"),
        pytest.param('"unknown_field"', id="string"),
        pytest.param("1", id="number"),
        pytest.param("null", id="null"),
        pytest.param("true", id="boolean"),
        pytest.param("{", id="truncated"),
        pytest.param('{"error":"\ud800"}', id="lone-surrogate"),
        pytest.param("[" * MAX_CARD_BYTES, id="deep-nesting"),
        pytest.param(_object_of(MAX_CARD_BYTES + 1), id="one-byte-over"),
        pytest.param(
            _object_of(MAX_CARD_BYTES + 1, "é"),
            id="one-byte-over-in-fewer-characters",
        ),
    ],
)
def test_a_card_must_be_one_canonical_json_object_within_its_limit(
    card: str,
) -> None:
    with pytest.raises(GenerationError) as caught:
        follow_up_prompt(_first_turn(), "{}", card)

    assert caught.value.code == "follow_up_invalid"


def test_a_card_shares_the_prompt_byte_budget() -> None:
    prompt = _first_turn()
    card = _object_of(MAX_CARD_BYTES)
    last = FOLLOW_UP_TEXT + COUNTEREXAMPLE_PREFIX + card
    used = sum(len(m.content.encode("utf-8")) for m in prompt.messages)
    room = MAX_PROMPT_BYTES - used - len(last.encode("utf-8"))

    continued = follow_up_prompt(prompt, "x" * room, card)
    bare = follow_up_prompt(prompt, "x" * (room + 1))

    assert sum(len(m.content.encode("utf-8")) for m in continued.messages) == (
        MAX_PROMPT_BYTES
    )
    assert bare.messages[3].content == FOLLOW_UP_TEXT
    with pytest.raises(GenerationError) as caught:
        follow_up_prompt(prompt, "x" * (room + 1), card)
    assert caught.value.code == "prompt_too_large"


def test_committed_prepared_files_reserialize_byte_for_byte() -> None:
    """Accepting a second turn changes no committed prompt file's bytes.

    Every digest a prepare, a run manifest or a score recorded over these
    files is therefore still the digest of the same bytes. A first turn has
    two messages. Only an arm run of a committed repair plan, first run or
    re-run, a test seed or a published run alike, may hold more: its bare
    and counterexample prompts add the counted answer and the follow-up
    turn, while its resample re-sends the first turn. CI runs this test
    with docs/ mounted, since the test image carries no docs/ tree.
    """
    if not _RESULTS.is_dir():
        pytest.skip("the test image carries no docs/ tree")
    paths = sorted(_RESULTS.glob("*/prepared/*.json"))
    arms = {
        run_id: arm
        for plan in _RESULTS.glob(f"*/{PLAN_PATH.as_posix()}")
        for arm in ARMS
        for run_id in arm_run_ids(plan.parent.parent.name, arm)
    }

    assert paths
    for path in paths:
        data = path.read_bytes()
        batch = PreparedBatchV1.model_validate_json(data)
        arm = arms.get(path.parent.parent.name)
        turns = 2 if arm in (None, "resample") else 4
        assert (canonical_json(batch) + "\n").encode("utf-8") == data, path
        assert all(len(p.messages) == turns for p in batch.prompts), path
