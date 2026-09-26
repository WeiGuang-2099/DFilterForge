"""The test freeze record: what it holds, what it admits, how it is written."""

import dataclasses
from datetime import datetime
from datetime import timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError
import pytest

from dfilterforge import held_out
from dfilterforge.canonical import canonical_json
from dfilterforge.completions import CatalogIdentityV1
from dfilterforge.completions import PreparedConditionV1
from dfilterforge.completions import PrepareManifestV1
from dfilterforge.generation import ConditionLabel
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import RetrievalV1
from dfilterforge.held_out import admit_prepare
from dfilterforge.held_out import HeldOutError
from dfilterforge.held_out import HeldOutFreezeV1
from dfilterforge.held_out_digests import frozen_digests
from dfilterforge.held_out_digests import main
from dfilterforge.model_feedback import feedback_labels_sha256
from dfilterforge.model_feedback import FeedbackProbes
from dfilterforge.model_feedback import generate_feedback_probes
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import ModelSplitArtifacts

# The freeze commit sets this, so from then on a missing record fails.
_FROZEN = True
_ROOT = Path(__file__).parents[1]
_DIGEST_KEYS = frozenset(
    {
        "inputs",
        "gold",
        "gold_hash",
        "feedback_labels",
        "semantic-31",
        "semantic-37",
        "semantic-43",
        "semantic-35",
    }
)
_CONDITIONS: dict[ConditionLabel, tuple[OutputContractV1, RetrievalV1]] = {
    "C1": (OutputContractV1.DISPLAY_FILTER, RetrievalV1.NONE),
    "C2": (OutputContractV1.DISPLAY_FILTER, RetrievalV1.LEXICAL),
    "C3": (OutputContractV1.TYPED_IR, RetrievalV1.NONE),
    "C4": (OutputContractV1.TYPED_IR, RetrievalV1.LEXICAL),
}


def _conditions(
    labels: tuple[ConditionLabel, ...],
) -> tuple[PreparedConditionV1, ...]:
    """Records two prompts for each named condition, in the given order."""
    return tuple(
        PreparedConditionV1(
            label=label,
            output_contract=_CONDITIONS[label][0],
            retrieval=_CONDITIONS[label][1],
            path=f"prepared/{label}.json",
            sha256="c" * 64,
            system_prompt_sha256="d" * 64,
            prompt_count=2,
        )
        for label in labels
    )


def _test_prepare(**overrides: Any) -> PrepareManifestV1:
    """Builds a two-item test prepare manifest over C1 to C4."""
    values: dict[str, Any] = {
        "prepare_id": "test-fixture",
        "created_at": datetime(2026, 9, 25, tzinfo=timezone.utc),
        "source_revision": "revision",
        "source_files": {"scripts/model_run.py": "a" * 64},
        "split": "test",
        "item_ids": ("mei-1001", "mei-1002"),
        "model_inputs_sha256": "b" * 64,
        "catalog": CatalogIdentityV1(
            file_name="catalog.sqlite3",
            file_sha256="e" * 64,
            sqlite_sha256="e" * 64,
            catalog_hash="f" * 64,
            tshark_version="4.6.8",
        ),
        "top_k": 16,
        "conditions": _conditions(tuple(_CONDITIONS)),
    }
    values.update(overrides)
    return PrepareManifestV1(**values)


def _written(prepare: PrepareManifestV1) -> bytes:
    """Returns the bytes ``scripts/model_run.py`` writes for a manifest."""
    return (canonical_json(prepare) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record_fields(**overrides: Any) -> dict[str, Any]:
    """Returns the fields of a valid record, with some replaced."""
    values: dict[str, Any] = {
        "prepare": _test_prepare(),
        "digests": {"inputs": "1" * 64},
        "admitted_prepares": (_sha256(_written(_test_prepare())),),
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"prepare": _test_prepare(split="dev")}, id="dev_prepare"),
        pytest.param(
            {
                "prepare": _test_prepare(
                    conditions=_conditions(("C1", "C2", "C3"))
                )
            },
            id="three_conditions",
        ),
        pytest.param(
            {
                "prepare": _test_prepare(
                    conditions=_conditions(("C2", "C1", "C3", "C4"))
                )
            },
            id="out_of_order",
        ),
        pytest.param({"admitted_prepares": ()}, id="no_admitted"),
        pytest.param(
            {"admitted_prepares": tuple(f"{n:064x}" for n in range(33))},
            id="too_many_admitted",
        ),
        pytest.param(
            {"admitted_prepares": ("2" * 64, "2" * 64)},
            id="repeated_admitted",
        ),
        pytest.param({"admitted_prepares": ("x",)}, id="bad_admitted"),
        pytest.param({"digests": {"inputs": "x"}}, id="bad_digest"),
    ],
)
def test_a_record_holds_one_full_test_prepare(
    overrides: dict[str, Any],
) -> None:
    """The frozen prepare is a four-condition test prepare, admitted once."""
    assert HeldOutFreezeV1(**_record_fields()).prepare.split == "test"

    with pytest.raises(ValidationError):
        HeldOutFreezeV1(**_record_fields(**overrides))


def test_a_dev_prompt_set_never_reads_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neither a missing nor a broken record can stop a dev pass."""
    path = tmp_path / "held_out_freeze.json"
    monkeypatch.setattr(held_out, "RECORD_PATH", path)

    admit_prepare("dev", b"anything")
    path.write_bytes(b"{")
    admit_prepare("dev", b"anything")

    with pytest.raises(HeldOutError) as error:
        admit_prepare("test", b"anything")
    assert error.value.code == "freeze_record_invalid"


def test_admission_reads_a_bounded_record_and_admits_only_its_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The frozen prepare and a later one pass; nothing else does."""
    path = tmp_path / "held_out_freeze.json"
    monkeypatch.setattr(held_out, "RECORD_PATH", path)
    frozen = _written(_test_prepare())
    later = _written(_test_prepare(prepare_id="test-later"))
    record = HeldOutFreezeV1(
        prepare=_test_prepare(),
        digests={},
        admitted_prepares=(_sha256(frozen), _sha256(later)),
    )
    text = canonical_json(record).encode("utf-8")
    # Trailing whitespace keeps the JSON valid, so only the size refuses.
    largest = text.ljust(held_out.MAX_RECORD_BYTES)

    def _code(data: bytes) -> str:
        with pytest.raises(HeldOutError) as error:
            admit_prepare("test", data)
        return error.value.code

    assert _code(frozen) == "freeze_record_missing"
    path.write_bytes(b"{")
    assert _code(frozen) == "freeze_record_invalid"
    path.write_bytes(b"{}")
    assert _code(frozen) == "freeze_record_invalid"
    path.write_bytes(largest + b" ")
    assert _code(frozen) == "freeze_record_invalid"
    path.unlink()
    path.mkdir()
    assert _code(frozen) == "freeze_record_invalid"
    path.rmdir()
    path.write_bytes(largest)
    admit_prepare("test", frozen)
    admit_prepare("test", later)
    assert _code(frozen.replace(b"revision", b"revisiom")) == "test_not_frozen"
    # The same manifest in other bytes: only the exact bytes are admitted.
    assert _code(frozen[:-1] + b" \n") == "test_not_frozen"


@pytest.fixture(name="split", scope="module")
def fixture_split(
    tmp_path_factory: pytest.TempPathFactory,
) -> ModelSplitArtifacts:
    return generate_model_split(tmp_path_factory.mktemp("split"))


@pytest.fixture(name="feedback", scope="module")
def fixture_feedback(split: ModelSplitArtifacts) -> FeedbackProbes:
    return generate_feedback_probes(split)


def _test_item_ids(split: ModelSplitArtifacts) -> tuple[str, ...]:
    """Returns the test item IDs of a generated split in file order."""
    return tuple(item.item_id for item in split.inputs if item.split == "test")


def _edited(
    split: ModelSplitArtifacts, side: str, edit: str
) -> ModelSplitArtifacts:
    """Rewords one item or rationale, widens one filter or swaps two routes."""
    gold = split.gold
    if edit == "intent":
        inputs = list(split.inputs)
        index = next(n for n, item in enumerate(inputs) if item.split == side)
        inputs[index] = inputs[index].model_copy(
            update={"intent": inputs[index].intent + " now"}
        )
        return dataclasses.replace(split, inputs=tuple(inputs))
    if edit == "rationale":
        non_ready = list(gold.non_ready)
        index = next(
            n for n, case in enumerate(non_ready) if case.split == side
        )
        non_ready[index] = non_ready[index].model_copy(
            update={"rationale": non_ready[index].rationale + " now"}
        )
        return dataclasses.replace(
            split, gold=gold.model_copy(update={"non_ready": tuple(non_ready)})
        )
    if edit == "filter":
        cases = list(gold.cases)
        index = next(
            n for n, case in enumerate(cases) if case.spec.split == side
        )
        spec = cases[index].spec.model_copy(
            update={
                "reference_filter": cases[index].spec.reference_filter
                + " && tcp"
            }
        )
        cases[index] = cases[index].model_copy(update={"spec": spec})
        return dataclasses.replace(
            split, gold=gold.model_copy(update={"cases": tuple(cases)})
        )
    first, second = {
        "dev": ("mei-0001", "mei-0003"),
        "test": ("mei-1001", "mei-1003"),
    }[side]
    routes = dict(gold.item_to_case)
    assert routes[first] != routes[second]
    routes[first], routes[second] = routes[second], routes[first]
    return dataclasses.replace(
        split, gold=gold.model_copy(update={"item_to_case": routes})
    )


def _reframed(feedback: FeedbackProbes, side: str) -> FeedbackProbes:
    """Adds one expected frame to one ready case's feedback expectation."""
    specs = dict(feedback.specs)
    case_id = next(key for key, spec in specs.items() if spec.split == side)
    (probe,) = specs[case_id].probes
    frames = (*probe.expected_frames, max(probe.expected_frames, default=0) + 1)
    probe = probe.model_copy(update={"expected_frames": frames})
    specs[case_id] = specs[case_id].model_copy(update={"probes": (probe,)})
    return FeedbackProbes(feedback.capture_dir, feedback.probes, specs)


def _test_captures(
    split: ModelSplitArtifacts, feedback: FeedbackProbes
) -> dict[str, str]:
    """Maps each test scored and feedback probe to its recorded capture."""
    specs = (
        *(case.spec for case in split.gold.cases),
        *feedback.specs.values(),
    )
    return {
        probe.probe_id: probe.capture_sha256
        for spec in specs
        if spec.split == "test"
        for probe in spec.probes
    }


@pytest.mark.parametrize(
    ("side", "edit", "moved"),
    [
        pytest.param("dev", "intent", set[str](), id="dev_intent"),
        pytest.param("dev", "filter", set[str](), id="dev_filter"),
        pytest.param("dev", "routing", set[str](), id="dev_routing"),
        pytest.param("dev", "rationale", set[str](), id="dev_rationale"),
        pytest.param("dev", "frames", set[str](), id="dev_frames"),
        pytest.param("test", "intent", {"inputs"}, id="test_intent"),
        pytest.param("test", "filter", {"gold", "gold_hash"}, id="test_filter"),
        pytest.param("test", "routing", {"gold"}, id="test_routing"),
        pytest.param(
            "test", "rationale", {"gold", "gold_hash"}, id="test_rationale"
        ),
        pytest.param("test", "frames", {"feedback_labels"}, id="test_frames"),
    ],
)
def test_the_digests_cover_the_test_split_and_nothing_of_dev(
    split: ModelSplitArtifacts,
    feedback: FeedbackProbes,
    side: str,
    edit: str,
    moved: set[str],
) -> None:
    """A test edit after the freeze fails the record test; a dev edit never.

    A routing swap moves only the routing-inclusive digest: the published
    gold hash cannot see it, which is why the record holds both. Non-ready
    gold moves both; a feedback label moves only the value the adequacy
    receipt quotes, and each capture digest is the one its probe records.
    """
    before = frozen_digests(split, feedback)
    after = (
        frozen_digests(split, _reframed(feedback, side))
        if edit == "frames"
        else frozen_digests(_edited(split, side, edit), feedback)
    )

    captures = {
        name: digest
        for name, digest in before.items()
        if name.startswith("semantic-")
    }
    assert set(before) == _DIGEST_KEYS
    assert before["feedback_labels"] == feedback_labels_sha256(feedback, "test")
    assert captures == _test_captures(split, feedback)
    assert {name for name in before if after[name] != before[name]} == moved


def test_the_writer_records_one_prepare_and_never_replaces_a_record(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    split: ModelSplitArtifacts,
    feedback: FeedbackProbes,
) -> None:
    """The record is computed from a test prepare and the code, then kept."""
    prepare = _test_prepare(item_ids=_test_item_ids(split))
    data = _written(prepare)
    prepare_dir = tmp_path / "test-fixture"
    prepare_dir.mkdir()
    (prepare_dir / "prepare.json").write_bytes(data)
    output = tmp_path / "held_out_freeze.json"
    argv = ["--prepare-dir", str(prepare_dir), "--output", str(output)]

    assert main(argv) == 0

    written = output.read_bytes()
    record = HeldOutFreezeV1.model_validate_json(written)
    digests = frozen_digests(split, feedback)
    assert record.prepare == prepare
    assert record.admitted_prepares == (_sha256(data),)
    assert record.digests == digests
    printed: dict[str, str] = json.loads(capsys.readouterr().out)
    assert printed == {"prepare": _sha256(data), **digests}

    with pytest.raises(HeldOutError) as error:
        main(argv)
    assert error.value.code == "record_exists"
    assert output.read_bytes() == written

    dev_output = tmp_path / "dev.json"
    (prepare_dir / "prepare.json").write_bytes(
        _written(_test_prepare(split="dev"))
    )
    with pytest.raises(ValidationError):
        main(["--prepare-dir", str(prepare_dir), "--output", str(dev_output)])
    assert not dev_output.exists()


def test_the_frozen_record_matches_the_regenerated_test_split(
    split: ModelSplitArtifacts, feedback: FeedbackProbes
) -> None:
    """A committed record names the test split the code regenerates.

    Its digests and frozen items must match, and its embedded manifest must
    hash to its first admitted digest, which ties every prepare-side field
    to the admitted bytes without the results tree.
    """
    if not _FROZEN and not held_out.RECORD_PATH.exists():
        pytest.skip("no freeze record yet")
    record = held_out.load_record()
    assert record is not None, "the freeze record is missing"

    assert record.digests == frozen_digests(split, feedback)
    assert record.prepare.item_ids == _test_item_ids(split)
    assert _sha256(_written(record.prepare)) == record.admitted_prepares[0]


def test_the_committed_test_prompts_and_quoted_digests_are_the_record() -> None:
    """The committed frozen prompt set is the admitted one, quoted in full.

    The test image carries no docs/ tree, so the record test cannot see the
    committed copy. Without this host test a stale copy would first show as
    ``prepared_drift`` at publish, after the paid requests, and a stale
    quote in the protocol would never show.
    """
    results = _ROOT / "docs" / "results"
    if not results.is_dir():
        pytest.skip("the test image carries no docs/ tree")
    record = held_out.load_record()
    assert record is not None, "the freeze record is missing"
    prepare = results / record.prepare.prepare_id / "prepare.json"
    protocol = (_ROOT / "docs" / "protocol.md").read_text(encoding="utf-8")
    quoted = {
        "prepare": record.admitted_prepares[0],
        "inputs": record.digests["inputs"],
        "gold and routing": record.digests["gold"],
        "gold hash": record.digests["gold_hash"],
        "feedback labels": record.digests["feedback_labels"],
    }

    assert _sha256(prepare.read_bytes()) == record.admitted_prepares[0]
    for label, digest in quoted.items():
        assert f"{label} `{digest[:12]}`" in " ".join(protocol.split()), label
