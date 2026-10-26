"""Training examples a few-shot prompt shows: the pool and the rule.

The few-shot row of the self-served ladder shows the base model, beside
each request, eight answered requests from training set v1, the rows SFT
learned from, chosen by the words they share with the request. The rule
reads the request text and nothing else: no item id, split, gold or
retrieval output. It uses integers only, so a rebuild anywhere picks the
same rows in the same order.

Words are runs of lowercase letters and digits, as the training grammar
counts them, less the sixteen words of its request frames ("Show packets
that ...", "Keep only packets that ..."), which every training request
carries. Rows rank by more shared words, then fewer words of their own
that the request lacks, then training id; the best eight are shown best
last, next to the request.
"""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import hashlib
import json
from pathlib import Path
import re
import zlib

from dfilterforge.errors import DFilterForgeError
from dfilterforge.generation import ShownExampleV1

RULE = "word-overlap/1"
FEW_SHOT_K = 8
POOL_PATH = "data/train/v1/sft.jsonl.gz"
# The decompressed sft.jsonl of training set v1, the digest that
# data/train/v1/sft-manifest.json records.
POOL_SHA256 = "4677e902ebd4483a24314bdcc695c762276e1ab6bf0a9132ccc08ff24163ce07"
# The words of train_combos.FRAMES, written out so the training grammar
# stays outside the prompt side; a test holds the two equal.
FRAME_WORDS = frozenset(
    {
        "all",
        "filter",
        "find",
        "for",
        "give",
        "i",
        "keep",
        "list",
        "me",
        "need",
        "only",
        "packets",
        "show",
        "that",
        "the",
        "which",
    }
)
_WORD = re.compile(r"[a-z0-9]+")
_INPUT_PREFIX = "INPUT_JSON\n"


class FewShotError(DFilterForgeError):
    """A pool or selection failure with a stable public code."""


@dataclass(frozen=True)
class FewShotPool:
    """The training rows examples are drawn from, and their digest."""

    rows: tuple[ShownExampleV1, ...]
    sha256: str


def words(text: str) -> frozenset[str]:
    """Returns a request's content words: its words less the frame words."""
    return frozenset(_WORD.findall(text.lower())) - FRAME_WORDS


def load_pool(path: Path) -> FewShotPool:
    """Reads the pool, refusing any bytes but training set v1's.

    Each row becomes one example: the request inside its INPUT_JSON and
    its SFT target, compact and in prompt key order.

    Raises:
        FewShotError: With ``pool_unreadable`` if the file cannot be read
            or decompressed, and with ``pool_mismatch`` if its content is
            not training set v1.
    """
    try:
        data = gzip.decompress(path.read_bytes())
    except (OSError, EOFError, zlib.error):
        raise FewShotError(
            "pool_unreadable", "The few-shot pool cannot be read"
        ) from None
    digest = hashlib.sha256(data).hexdigest()
    if digest != POOL_SHA256:
        raise FewShotError(
            "pool_mismatch", "The few-shot pool is not training set v1"
        )
    rows = tuple(_example(line) for line in data.decode("utf-8").splitlines())
    return FewShotPool(rows=rows, sha256=digest)


def _example(line: str) -> ShownExampleV1:
    """Returns one SFT row as an example; the digest vouches for its shape."""
    row = json.loads(line)
    user = row["messages"][1]["content"]
    payload = json.loads(user.removeprefix(_INPUT_PREFIX))
    return ShownExampleV1(
        train_id=row["id"], intent=payload["intent"], result=row["completion"]
    )


def select_examples(
    intent: str, pool: FewShotPool, k: int = FEW_SHOT_K
) -> tuple[ShownExampleV1, ...]:
    """Returns the ``k`` rows that best share a request's words, best last.

    Raises:
        FewShotError: With ``pool_too_small`` if the pool holds fewer than
            ``k`` rows or ``k`` is not positive.
    """
    if not 1 <= k <= len(pool.rows):
        raise FewShotError(
            "pool_too_small", f"The pool cannot supply {k} examples"
        )
    query = words(intent)

    def rank(row: ShownExampleV1) -> tuple[int, int, str]:
        own = words(row.intent)
        return (-len(query & own), len(own - query), row.train_id)

    return tuple(reversed(sorted(pool.rows, key=rank)[:k]))
