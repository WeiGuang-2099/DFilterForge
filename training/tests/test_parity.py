"""The sequence SFT trains on is the served prompt, the answer, the stop.

A server answering a scored C4 request renders its messages with the
Qwen3-1.7B chat template and thinking off, tokenizes that text without
adding special tokens, and stops at <|im_end|>. tests/test_sft_dataset.py
in the main package proves the messages are the ones scoring prepares;
this test proves the token sequence built from them is that render, then
the completion, then the stop token, and that the loss mask covers exactly
the completion. It needs the pinned tokenizer, which the training image
fetches at build time.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# pylint: disable-next=wrong-import-position
import train_sft

_THINKING_OFF = "<|im_start|>assistant\n<think>\n\n</think>\n\n"


def test_training_sequence_is_the_served_prompt_then_answer_and_stop():
    """Every row: render, completion, stop; labels on the completion only."""
    tokenizer = train_sft.load_tokenizer()
    assert tokenizer.eos_token == train_sft.STOP
    rows = train_sft.load_rows()
    assert {row["status"] for row in rows} == {"ready", "needs_clarification"}
    for row in rows:
        served = tokenizer.apply_chat_template(
            row["messages"],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        assert served.endswith(_THINKING_OFF)
        assert served.count("<think>") == 1
        assert all(m["content"] in served for m in row["messages"])
        answered = [
            *row["messages"],
            {"role": "assistant", "content": row["completion"]},
        ]
        assert tokenizer.apply_chat_template(
            answered, tokenize=False, enable_thinking=False
        ) == (served + row["completion"] + train_sft.STOP + "\n")
        encoded = train_sft.encode(tokenizer, row)
        ids, mask = encoded["input_ids"], encoded["completion_mask"]
        prompt = mask.count(0)
        assert mask == [0] * prompt + [1] * (len(ids) - prompt)
        assert (
            ids[:prompt]
            == tokenizer(served, add_special_tokens=False)["input_ids"]
        )
        assert (
            ids
            == tokenizer(
                served + row["completion"] + train_sft.STOP,
                add_special_tokens=False,
            )["input_ids"]
        )
        assert ids[-1] == tokenizer.eos_token_id
        assert (
            tokenizer.decode(ids[prompt:], skip_special_tokens=True)
            == row["completion"]
        )
