"""Non-ready gold: its record, its items and how scoring routes and hashes it."""

from pathlib import Path

from pydantic import ValidationError
import pytest

from dfilterforge import model_split
from dfilterforge.canonical import content_sha256
from dfilterforge.generation import GenerationInputV1
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import prepare_batch
from dfilterforge.generation import RetrievalV1
from dfilterforge.intent_ir import MissingSlot
from dfilterforge.model_cases import ModelNonReadyCase
from dfilterforge.model_cases import ModelNonReadyCaseV1
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import ModelGoldV1
from dfilterforge.run_store import gold_hash
from dfilterforge.run_store import ScoringError
from dfilterforge.run_store import selected_cases

_CLARIFY = ModelNonReadyCase(
    case_id="unnamed-server",
    split="dev",
    status="needs_clarification",
    paraphrases=(
        "Show all packets sent to the new file server.",
        "Find traffic headed for our new file server.",
    ),
    missing_slots=(MissingSlot.ADDRESS,),
    rationale="No host or network is given.",
)
_INEXPRESSIBLE = ModelNonReadyCase(
    case_id="five-largest",
    split="test",
    status="not_expressible",
    paraphrases=(
        "Show the five largest packets in the capture.",
        "Find the five biggest frames of the whole trace.",
    ),
    missing_slots=(),
    rationale="A ranking across packets is not a per-packet test.",
)


@pytest.fixture(name="split")
def fixture_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> model_split.ModelSplitArtifacts:
    """One split with a non-ready case in each of dev and test."""
    monkeypatch.setattr(
        model_split,
        "model_non_ready_cases",
        lambda: (_CLARIFY, _INEXPRESSIBLE),
    )
    return generate_model_split(tmp_path)


@pytest.mark.parametrize(
    ("status", "slots"),
    [
        ("needs_clarification", ()),
        ("not_expressible", (MissingSlot.PORT,)),
        ("needs_clarification", (MissingSlot.PORT, MissingSlot.PORT)),
    ],
)
def test_gold_slots_must_fit_the_gold_status(
    status: str, slots: tuple[MissingSlot, ...]
) -> None:
    with pytest.raises(ValidationError):
        ModelNonReadyCaseV1(
            case_id="a-case",
            split="dev",
            status=status,  # type: ignore[arg-type]
            missing_slots=slots,
            rationale="Why.",
        )


def test_non_ready_items_follow_every_ready_item(
    split: model_split.ModelSplitArtifacts,
) -> None:
    routes = split.gold.item_to_case
    ready_ids = [
        item_id
        for item_id, case_id in routes.items()
        if case_id not in {_CLARIFY.case_id, _INEXPRESSIBLE.case_id}
    ]
    non_ready_ids = sorted(set(routes) - set(ready_ids))

    assert split.gold.non_ready == (_CLARIFY.gold(), _INEXPRESSIBLE.gold())
    assert max(ready_ids) < min(non_ready_ids)
    first = len(ready_ids) + 1
    assert non_ready_ids == [f"mei-{first + step:04d}" for step in range(4)]
    by_id = {item.item_id: item for item in split.inputs}
    assert by_id[non_ready_ids[0]].intent == _CLARIFY.paraphrases[0]
    assert (by_id[non_ready_ids[0]].split, by_id[non_ready_ids[2]].split) == (
        "dev",
        "test",
    )


def test_routing_counts_non_ready_cases_like_ready_ones(
    split: model_split.ModelSplitArtifacts,
) -> None:
    gold = split.gold.model_dump()
    duplicated = {**gold, "non_ready": [gold["non_ready"][0]] * 2}
    clarify_items = sorted(
        item_id
        for item_id, case_id in gold["item_to_case"].items()
        if case_id == _CLARIFY.case_id
    )
    one_item = {
        **gold,
        "item_to_case": {
            key: value
            for key, value in gold["item_to_case"].items()
            if key != clarify_items[1]
        },
    }

    for bad in (duplicated, one_item):
        with pytest.raises(ValidationError):
            ModelGoldV1.model_validate(bad)


def _prompts(
    split: model_split.ModelSplitArtifacts, name: str
) -> list[model_split.ModelInputItemV1]:
    return [item for item in split.inputs if item.split == name]


def test_scoring_routes_non_ready_items_and_hashes_their_gold(
    split: model_split.ModelSplitArtifacts,
) -> None:
    batch = prepare_batch(
        [
            GenerationInputV1(
                item_id=item.item_id,
                intent=item.intent,
                user_assumptions=item.user_assumptions,
                split=item.split,
            )
            for item in _prompts(split, "dev")
        ],
        output_contract=OutputContractV1.DISPLAY_FILTER,
        retrieval=RetrievalV1.NONE,
    )

    routes, ready, non_ready = selected_cases(batch.prompts, split.gold, "dev")
    clarify_item = next(
        item.item_id
        for item in split.inputs
        if item.intent == _CLARIFY.paraphrases[0]
    )

    assert routes[clarify_item] == _CLARIFY.gold()
    assert non_ready == (_CLARIFY.gold(),)
    assert len(ready) == sum(
        case.spec.split == "dev" for case in split.gold.cases
    )
    # With no non-ready case the hash is the one committed summaries carry.
    assert gold_hash(ready) == content_sha256(ready)
    assert gold_hash(ready, non_ready) != gold_hash(ready)
    with pytest.raises(ScoringError) as error:
        selected_cases(batch.prompts, split.gold, "test")
    assert error.value.code == "split_violation"
