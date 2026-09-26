"""Digests of the frozen test split, and the one-time freeze record writer.

Run once, at the freeze, as ``python -m dfilterforge.held_out_digests
--prepare-dir DIR``: it regenerates the split in a temporary directory,
digests its test half and the test feedback labels, and writes the record
that :mod:`dfilterforge.held_out` reads, refusing to replace one. The
regenerated split is deleted with its directory; the record keeps only
digests of it.

The digests read gold and the feedback probe, so only this entry point and
the tests import this module; ``scripts/model_run.py`` must never load it.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import content_sha256
from dfilterforge.completions import PrepareManifestV1
from dfilterforge.held_out import HeldOutError
from dfilterforge.held_out import HeldOutFreezeV1
from dfilterforge.held_out import RECORD_PATH
from dfilterforge.model_feedback import feedback_labels_sha256
from dfilterforge.model_feedback import FeedbackProbes
from dfilterforge.model_feedback import generate_feedback_probes
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import ModelSplitArtifacts
from dfilterforge.run_store import gold_hash


def frozen_digests(
    artifacts: ModelSplitArtifacts, feedback: FeedbackProbes
) -> dict[str, str]:
    """Digests the test half of a generated split and its feedback labels.

    ``inputs`` covers the test model items in file order. ``gold`` covers
    the test ready and non-ready gold in gold order with the routing of
    every test item, which ``gold_hash``, the value a full test summary
    publishes, leaves out. ``feedback_labels`` is the value the adequacy
    receipt quotes for the test split. Each scored and feedback capture of
    the test split is keyed by its probe ID. No dev item, case or capture
    reaches any of them.

    Args:
        artifacts: A generated model split.
        feedback: The feedback probes generated beside it.

    Returns:
        The digests a freeze record holds, by name.
    """
    inputs = tuple(item for item in artifacts.inputs if item.split == "test")
    ready = tuple(
        case for case in artifacts.gold.cases if case.spec.split == "test"
    )
    non_ready = tuple(
        case for case in artifacts.gold.non_ready if case.split == "test"
    )
    routing = {
        item.item_id: artifacts.gold.item_to_case[item.item_id]
        for item in inputs
    }
    specs = (
        *(case.spec for case in ready),
        *(spec for spec in feedback.specs.values() if spec.split == "test"),
    )
    return {
        "inputs": content_sha256(inputs),
        "gold": content_sha256((ready, non_ready, routing)),
        "gold_hash": gold_hash(ready, non_ready),
        "feedback_labels": feedback_labels_sha256(feedback, "test"),
        **{
            probe.probe_id: probe.capture_sha256
            for spec in specs
            for probe in spec.probes
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Writes the freeze record for one test prepare directory, once.

    The record embeds the manifest, admits the SHA-256 of the exact
    ``prepare.json`` bytes read and holds the digests of a split regenerated
    from the code. It is validated before the output is created, and the
    output is created exclusively, so an existing record is never replaced.

    Args:
        argv: The arguments after the program name, or None for the
            process arguments.

    Returns:
        Zero once the record is written and its digests printed.

    Raises:
        HeldOutError: With ``record_exists`` when the output already exists.
        pydantic.ValidationError: When ``prepare.json`` is not a prepare
            manifest of the test split over C1 to C4.
        OSError: When ``prepare.json`` cannot be read or the output cannot
            be written.
    """
    parser = argparse.ArgumentParser(
        description="Write the test freeze record from one test prepare."
    )
    parser.add_argument("--prepare-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=RECORD_PATH)
    arguments = parser.parse_args(argv)
    prepare_dir = cast(Path, arguments.prepare_dir)
    output = cast(Path, arguments.output)
    data = (prepare_dir / "prepare.json").read_bytes()
    prepare = PrepareManifestV1.model_validate_json(data)
    with TemporaryDirectory(prefix="dfilterforge-freeze-") as staging:
        artifacts = generate_model_split(Path(staging))
        digests = frozen_digests(artifacts, generate_feedback_probes(artifacts))
    record = HeldOutFreezeV1(
        prepare=prepare,
        digests=digests,
        admitted_prepares=(hashlib.sha256(data).hexdigest(),),
    )
    text = (
        json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True)
        + "\n"
    )
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
    except FileExistsError:
        raise HeldOutError(
            "record_exists", "A freeze record already exists"
        ) from None
    print(canonical_json({"prepare": record.admitted_prepares[0], **digests}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
