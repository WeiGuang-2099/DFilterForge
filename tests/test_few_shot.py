"""Tests for the few-shot row's example pool and selection rule."""

import gzip
import json
from pathlib import Path
import re

import pytest

from dfilterforge.completions import PrepareManifestV1
from dfilterforge.few_shot import FewShotError
from dfilterforge.few_shot import FewShotPool
from dfilterforge.few_shot import FRAME_WORDS
from dfilterforge.few_shot import load_pool
from dfilterforge.few_shot import POOL_PATH
from dfilterforge.few_shot import POOL_SHA256
from dfilterforge.few_shot import select_examples
from dfilterforge.few_shot import words
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import ShownExampleV1
from dfilterforge.train_combos import FRAMES

_ROOT = Path(__file__).resolve().parents[1]
_RESULTS = _ROOT / "docs" / "results"
_RESULT = (
    '{"schema_version":"1.0","status":"not_expressible","assumptions":[],'
    '"clarifying_question":null,"missing_slots":[],"intent_ir":null}'
)


def _row(number: int, intent: str) -> ShownExampleV1:
    return ShownExampleV1(
        train_id=f"train-{number:04d}", intent=intent, result=_RESULT
    )


def test_examples_rank_by_shared_then_extra_words_then_id() -> None:
    pool = FewShotPool(
        rows=(
            _row(5, "Keep only packets that use tcp port 80."),
            _row(2, "Show packets that use tcp port 80."),
            _row(3, "Show packets that use tcp port 80 or udp."),
            _row(4, "Show packets that use tcp."),
            _row(1, "Show the packets that are arp."),
        ),
        sha256="0" * 64,
    )

    chosen = select_examples("Find the tcp port 80 packets", pool, k=4)

    # 2 and 5 share tcp, port and 80 with nothing extra but "use", so the
    # id decides; 3 adds "or udp"; 4 shares one word; frame words count
    # for nothing, so 1 shares none. Best last.
    assert [row.train_id for row in chosen] == [
        "train-0004",
        "train-0003",
        "train-0005",
        "train-0002",
    ]
    assert words("Keep only packets that use TCP.") == {"use", "tcp"}
    with pytest.raises(FewShotError) as refused:
        select_examples("tcp", pool, k=6)
    assert refused.value.code == "pool_too_small"


def test_frame_words_are_the_training_frames() -> None:
    framed = {
        word
        for frame in FRAMES
        for word in re.findall(r"[a-z0-9]+", frame.lower())
    }

    assert FRAME_WORDS == framed


def test_the_pool_is_training_set_v1(tmp_path: Path) -> None:
    pool = load_pool(_ROOT / POOL_PATH)
    requests = [
        json.loads(line)
        for line in (_ROOT / "data" / "train" / "v1" / "train.jsonl")
        .read_text("utf-8")
        .splitlines()
    ]

    assert pool.sha256 == POOL_SHA256
    assert [(row.train_id, row.intent) for row in pool.rows] == [
        (row["id"], row["request"]) for row in requests
    ]
    data = gzip.decompress((_ROOT / POOL_PATH).read_bytes())
    edited = tmp_path / "sft.jsonl.gz"
    edited.write_bytes(gzip.compress(data.replace(b"Show", b"show", 1)))
    with pytest.raises(FewShotError) as refused:
        load_pool(edited)
    assert refused.value.code == "pool_mismatch"
    corrupt = bytearray((_ROOT / POOL_PATH).read_bytes())
    corrupt[40] ^= 0xFF
    edited.write_bytes(bytes(corrupt))
    with pytest.raises(FewShotError) as unreadable:
        load_pool(edited)
    assert unreadable.value.code == "pool_unreadable"


def test_committed_few_shot_prompts_replay_from_the_pool() -> None:
    """Every committed few-shot prompt shows what the rule picks."""
    if not _RESULTS.is_dir():
        pytest.skip("the test image carries no docs/ tree")
    pool = load_pool(_ROOT / POOL_PATH)
    for manifest_path in sorted(_RESULTS.glob("*/prepare.json")):
        manifest = PrepareManifestV1.model_validate_json(
            manifest_path.read_bytes()
        )
        if manifest.few_shot is None:
            continue
        assert manifest.few_shot.pool_sha256 == pool.sha256
        batch = PreparedBatchV1.model_validate_json(
            (manifest_path.parent / "prepared" / "C4.json").read_bytes()
        )
        for prompt in batch.prompts:
            intent = json.loads(
                prompt.messages[1].content.removeprefix("INPUT_JSON\n")
            )["intent"]
            assert prompt.examples == select_examples(
                intent, pool, manifest.few_shot.k
            )
            assert all(row.intent != intent for row in prompt.examples or ())
