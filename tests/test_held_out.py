"""The test freeze record: what it must hold and which prompt sets it admits."""

from datetime import datetime
from datetime import timezone
import hashlib
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
