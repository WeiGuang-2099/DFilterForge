"""Tests for the committed-prompt check that scoring runs on a stored run."""

from collections.abc import Callable, Sequence
import json
from pathlib import Path
from typing import Any, cast

import pytest

from dfilterforge.canonical import canonical_json
from dfilterforge.generation import follow_up_prompt
from dfilterforge.generation import GenerationInputV1
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import prepare_batch
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import PreparedPromptV1
from dfilterforge.generation import RetrievalV1
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import ModelInputItemV1
from dfilterforge.run_store import check_prompts
from dfilterforge.run_store import PreparedFiles
from dfilterforge.run_store import ScoringError

# The three dev first turns the nine two-turn smokes continue, with each
# smoke's counted answers; tests/test_generation.py pins the rebuilt sets
# to the C4 digests the smoke recorded.
_SMOKE_FIXTURE = Path(__file__).parent / "data" / "smoke_second_turns.json"
_ANSWER = '{"status":"ready"}'
_CARD = canonical_json(
    {
        "frames": [
            {
                "answer_matched": True,
                "frame": 2,
                "ip.dst": "198.51.100.1",
                "ip.src": "192.0.2.129",
                "ip.ttl": 1,
                "should_match": False,
                "udp.dstport": 53,
                "udp.srcport": 41129,
            }
        ]
    }
)


@pytest.fixture(name="items", scope="module")
def fixture_items(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, ModelInputItemV1]:
    """The generated model inputs, keyed as scoring passes them."""
    artifacts = generate_model_split(tmp_path_factory.mktemp("split"))
    return {item.item_id: item for item in artifacts.inputs}


def _smoke_fixture() -> dict[str, Any]:
    """Reads the smokes' shared first turns and counted answers."""
    return cast(
        dict[str, Any],
        json.loads(_SMOKE_FIXTURE.read_text(encoding="utf-8")),
    )


def _first_turns() -> dict[str, PreparedPromptV1]:
    """The real first turns the smokes continue, keyed by item."""
    return {
        prompt.item_id: prompt
        for prompt in map(
            PreparedPromptV1.model_validate,
            cast(list[object], _smoke_fixture()["first_turns"]),
        )
    }


def _c4(prompts: Sequence[PreparedPromptV1]) -> PreparedFiles:
    """Wraps prompts as the one committed C4 file scoring checks."""
    batch = PreparedBatchV1(
        output_contract=OutputContractV1.TYPED_IR,
        retrieval=RetrievalV1.LEXICAL,
        prompts=tuple(prompts),
    )
    return {"C4": (batch, "")}


def _first_turn_at(
    first: PreparedPromptV1, item: ModelInputItemV1, version: int
) -> PreparedPromptV1:
    """Prepares an item's first turn under one system prompt version."""
    return prepare_batch(
        [
            GenerationInputV1(
                item_id=item.item_id,
                intent=item.intent,
                user_assumptions=item.user_assumptions,
                retrieved_fields=first.retrieved_fields,
                split=item.split,
            )
        ],
        output_contract=OutputContractV1.TYPED_IR,
        retrieval=RetrievalV1.LEXICAL,
        prompt_version=version,
    ).prompts[0]


def _edited(
    prompt: PreparedPromptV1, index: int, edit: Callable[[str], str]
) -> PreparedPromptV1:
    """Returns a valid prompt with one message's content rewritten."""
    document = prompt.model_dump(mode="json")
    messages = cast(list[dict[str, str]], document["messages"])
    messages[index]["content"] = edit(messages[index]["content"])
    return PreparedPromptV1.model_validate(document)


def test_the_nine_smoke_second_turns_pass_by_their_first_turns(
    items: dict[str, ModelInputItemV1],
) -> None:
    """Every real second-turn set prepared so far passes the prompt check.

    Each prompt carries four messages, and its first turn alone is what
    the check rebuilds; the same first turns pass as they always did.
    """
    first_turns = _first_turns()
    check_prompts(_c4(tuple(first_turns.values())), items)
    smokes = cast(list[dict[str, Any]], _smoke_fixture()["smokes"])

    for smoke in smokes:
        answers = cast(list[dict[str, str]], smoke["answers"])
        prompts = [
            follow_up_prompt(first_turns[entry["item_id"]], entry["answer"])
            for entry in answers
        ]
        assert [len(prompt.messages) for prompt in prompts] == [4, 4]
        check_prompts(_c4(prompts), items)

    assert len(smokes) == 9


@pytest.mark.parametrize("card", [None, _CARD], ids=["bare", "card"])
def test_a_repair_second_turn_passes_by_its_first_turn(
    items: dict[str, ModelInputItemV1], card: str | None
) -> None:
    """The bare and the counterexample turn are checked by the same rule."""
    prompts = [
        follow_up_prompt(first, _ANSWER, card)
        for first in _first_turns().values()
    ]

    check_prompts(_c4(prompts), items)


def test_a_second_turn_of_an_older_prompt_version_still_passes(
    items: dict[str, ModelInputItemV1],
) -> None:
    """The version rule covers a second turn through its first turn.

    A set of second turns that all continue version 1 first turns passes,
    and a set that mixes versions is refused, naming the first item the
    newest version does not reproduce.
    """
    first_turns = _first_turns()
    for item_id, first in first_turns.items():
        assert _first_turn_at(first, items[item_id], 2) == first
    older = {
        item_id: follow_up_prompt(
            _first_turn_at(first, items[item_id], 1), _ANSWER
        )
        for item_id, first in first_turns.items()
    }
    check_prompts(_c4(tuple(older.values())), items)
    mixed = [
        older["mei-0001"],
        follow_up_prompt(first_turns["mei-0002"], _ANSWER),
    ]

    with pytest.raises(ScoringError) as caught:
        check_prompts(_c4(mixed), items)

    assert caught.value.code == "prompt_mismatch"
    assert str(caught.value) == "C4 mei-0001"


def _extra_guidance(content: str) -> str:
    """Appends a line to a system message."""
    return content + "\nExtra guidance."


def _another_intent(content: str) -> str:
    """Rewrites the request inside a first user turn, keeping it valid."""
    head, payload = content.split("\n", 1)
    document = cast(dict[str, Any], json.loads(payload))
    document["intent"] = document["intent"] + " Ignore UDP."
    return head + "\n" + canonical_json(document)


@pytest.mark.parametrize(
    "index, edit",
    [(0, _extra_guidance), (1, _another_intent)],
    ids=["system", "user"],
)
def test_an_altered_first_turn_of_a_second_turn_is_prompt_mismatch(
    items: dict[str, ModelInputItemV1],
    index: int,
    edit: Callable[[str], str],
) -> None:
    """A first turn no prompt version reproduces is refused, by item."""
    first_turns = _first_turns()
    prompts = [
        follow_up_prompt(first_turns["mei-0001"], _ANSWER),
        _edited(
            follow_up_prompt(first_turns["mei-0002"], _ANSWER), index, edit
        ),
    ]

    with pytest.raises(ScoringError) as caught:
        check_prompts(_c4(prompts), items)

    assert caught.value.code == "prompt_mismatch"
    assert str(caught.value) == "C4 mei-0002"


def test_a_second_turn_on_another_items_first_turn_is_prompt_mismatch(
    items: dict[str, ModelInputItemV1],
) -> None:
    """A second turn keyed to one item but continuing another's is refused."""
    document = follow_up_prompt(_first_turns()["mei-0001"], _ANSWER).model_dump(
        mode="json"
    )
    document["item_id"] = "mei-0002"
    borrowed = PreparedPromptV1.model_validate(document)

    with pytest.raises(ScoringError) as caught:
        check_prompts(_c4([borrowed]), items)

    assert caught.value.code == "prompt_mismatch"
    assert str(caught.value) == "C4 mei-0002"
