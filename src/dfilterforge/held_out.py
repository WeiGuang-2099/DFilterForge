"""The committed test freeze record and the check every test call passes.

``held_out_freeze.json`` beside this module holds the frozen test prepare
manifest, digests of the test inputs, gold, captures and feedback labels,
and the SHA-256 of every ``prepare.json`` a test call may answer. The call
step refuses a non-dev prompt set the record does not admit before any
client exists.

``scripts/model_run.py`` loads this module, so it reads the record and
nothing else: it imports no gold, split or feedback module, and an import
contract enforces that. It is not one of the files a prepare hashes, so a
later prompt set, such as a repair round's, is admitted by a commit to the
record alone.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field
from pydantic import model_validator

from dfilterforge.completions import PrepareManifestV1
from dfilterforge.errors import DFilterForgeError
from dfilterforge.intent_ir import FrozenModel

# Read at call time, so the tests can point it elsewhere.
RECORD_PATH = Path(__file__).with_name("held_out_freeze.json")
MAX_RECORD_BYTES = 1 << 20
_MAX_ADMITTED = 32
_FROZEN_LABELS = ("C1", "C2", "C3", "C4")

_Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class HeldOutError(DFilterForgeError, ValueError):
    """A refused test call or an unusable freeze record."""


class HeldOutFreezeV1(FrozenModel):
    """The frozen test prepare, its gold-side digests and what is admitted.

    ``prepare`` is the frozen manifest itself, so the record names the
    items, the prompt file and system prompt digests, the catalog, the
    retrieval depth and the source digests without the results tree, which
    the test image does not carry. ``digests`` maps ``inputs``, ``gold``
    (with item routing), ``gold_hash``, ``feedback_labels`` and each
    capture's probe id to its SHA-256. ``admitted_prepares`` lists the
    ``prepare.json`` digests a test call may answer, the frozen one first.
    """

    schema_version: Literal["held-out-freeze/1.0"] = "held-out-freeze/1.0"
    prepare: PrepareManifestV1
    digests: dict[str, _Sha256]
    admitted_prepares: tuple[_Sha256, ...] = Field(
        min_length=1, max_length=_MAX_ADMITTED
    )

    @model_validator(mode="after")
    def validate_frozen_prepare(self) -> "HeldOutFreezeV1":
        """Requires a four-condition test prepare and no repeated entry."""
        if self.prepare.split != "test":
            raise ValueError("the frozen prepare must be a test prepare")
        labels = tuple(condition.label for condition in self.prepare.conditions)
        if labels != _FROZEN_LABELS:
            raise ValueError("the frozen prepare holds C1 to C4 in order")
        if len(set(self.admitted_prepares)) != len(self.admitted_prepares):
            raise ValueError("an admitted prepare is listed twice")
        return self


def load_record() -> HeldOutFreezeV1 | None:
    """Reads the committed record, or returns None when there is none.

    Returns:
        The validated record, or None when ``RECORD_PATH`` does not exist.

    Raises:
        HeldOutError: With ``freeze_record_invalid`` if the record cannot
            be read, is over ``MAX_RECORD_BYTES`` or does not validate.
    """
    if not RECORD_PATH.exists():
        return None
    try:
        with RECORD_PATH.open("rb") as stream:
            data = stream.read(MAX_RECORD_BYTES + 1)
        if len(data) > MAX_RECORD_BYTES:
            raise ValueError("the freeze record is over its size bound")
        return HeldOutFreezeV1.model_validate_json(data)
    except (OSError, ValueError):
        raise HeldOutError(
            "freeze_record_invalid", "The freeze record is not usable"
        ) from None


def admit_prepare(split: str, prepare_bytes: bytes) -> None:
    """Refuses a non-dev prompt set the committed record does not admit.

    A dev prompt set never reads the record, so a broken record cannot
    stop dev work, and a split added later is refused until admitted.

    Args:
        split: The split the prepare manifest names.
        prepare_bytes: The exact bytes of that ``prepare.json``.

    Raises:
        HeldOutError: With ``freeze_record_missing`` when no record is
            committed, ``freeze_record_invalid`` when it is unusable, and
            ``test_not_frozen`` when it does not admit these bytes.
    """
    if split == "dev":
        return
    record = load_record()
    if record is None:
        raise HeldOutError(
            "freeze_record_missing", "No test freeze record is committed"
        )
    digest = hashlib.sha256(prepare_bytes).hexdigest()
    if digest not in record.admitted_prepares:
        raise HeldOutError(
            "test_not_frozen",
            "The freeze record does not admit this test prompt set",
        )
