"""One-off: replays committed dev answers on the feedback probes.

For every executed answer in docs/results/*/scored/outcomes.jsonl (strong
exact, shortcut or silent-wrong), runs its candidate filter on its case's
feedback probe and compares the frames with the feedback labels. Prints one
JSON object with per-outcome counts. Runs in the test image with the tree
bind-mounted; the results tree is mounted at /results.
"""

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from dfilterforge.model_feedback import generate_feedback_probes
from dfilterforge.model_split import generate_model_split
from dfilterforge.runner import TsharkRunner

_EXECUTED = ("strong_exact", "shortcut", "silent_wrong")


def main() -> int:
    variant = sys.argv[1]
    runner = TsharkRunner()
    rows = []
    with TemporaryDirectory() as staging:
        feedback = generate_feedback_probes(generate_model_split(Path(staging)))
        for outcomes in sorted(
            Path("/results").glob("*/scored/outcomes.jsonl")
        ):
            run = outcomes.parent.parent.name
            for line in outcomes.read_text(encoding="utf-8").splitlines():
                item = json.loads(line)
                if item["outcome"] not in _EXECUTED:
                    continue
                spec = feedback.specs[item["case_id"]]
                (expected,) = spec.probes
                capture = feedback.capture_dir / f"{expected.probe_id}.pcap"
                text = item["candidate_filter"]
                if text is None:
                    # A typed answer's compiled filter is in its receipt.
                    receipt = (
                        outcomes.parent
                        / "receipts"
                        / item["condition"]
                        / f"{item['item_id']}.json"
                    )
                    text = json.loads(receipt.read_text(encoding="utf-8"))[
                        "candidate_filter"
                    ]
                frames = runner.run(capture, text).frames
                rows.append(
                    {
                        "run": run,
                        "condition": item["condition"],
                        "item_id": item["item_id"],
                        "case_id": item["case_id"],
                        "outcome": item["outcome"],
                        "separated": tuple(frames) != expected.expected_frames,
                    }
                )
    summary = {}
    for outcome in _EXECUTED:
        chosen = [row for row in rows if row["outcome"] == outcome]
        summary[outcome] = {
            "items": len(chosen),
            "separated": sum(row["separated"] for row in chosen),
            "distinct_cases": len({row["case_id"] for row in chosen}),
        }
    print(
        json.dumps(
            {"variant": variant, "summary": summary, "rows": rows},
            indent=1,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
