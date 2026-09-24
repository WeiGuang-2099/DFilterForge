"""Docker-only comparison of the shortcut policy with and without catalog types.

Full reads each mentioned field's tshark type from the frozen catalog, so a
frame reference such as dns.response_in or a time such as tcp.time_delta is a
capture-position shortcut. Simplified is the same policy given no types: it
keeps every name, generator-identifier and capture-constant rule and drops
only the catalog type lookup.

The receipt records four things: how many frame-number and time fields of the
catalog each variant catches; how each variant scores a fixed list of shortcut
filters, written before any was run, on the real probes of their cases;
whether either variant flags a gold filter, a gold target, a single-site
mutant or a committed model answer; and what the catalog lookup costs.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import statistics
from tempfile import TemporaryDirectory
from time import perf_counter

from dfilterforge.canonical import file_sha256
from dfilterforge.catalog_runtime import DEFAULT_CATALOG_PATH
from dfilterforge.catalog_runtime import tshark_types
from dfilterforge.compiler import compile_intent
from dfilterforge.field_catalog import parse_tshark_fields
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import model_semantic_cases
from dfilterforge.model_split import ModelSemanticCase
from dfilterforge.model_split import ModelSplitArtifacts
from dfilterforge.mutants import single_site_mutants
from dfilterforge.runner import TsharkRunner
from dfilterforge.shortcuts import find_shortcuts
from dfilterforge.shortcuts import POSITION_TYPES
from dfilterforge.shortcuts import references

_SCHEMA_VERSION = "shortcut-ablation/1.0"
_SPLIT_PROBES = {
    "dev": ("semantic-11", "semantic-17", "semantic-23"),
    "test": ("semantic-31", "semantic-37", "semantic-43"),
}
# (case, filter): each adds or swaps in one shortcut next to the case's own
# reference, written before any of them was executed.
_WITNESSES: tuple[tuple[str, str], ...] = (
    ("udp-expiring-ttl", "udp && ip.ttl <= 1 && !dns.response_in"),
    ("tcp-expiring-ttl", "tcp && ip.ttl <= 1 && !(tcp.time_delta > 100)"),
    ("tcp-expiring-ttl", "tcp && ip.ttl <= 1 && frame.number >= 1"),
    ("ack-to-https", "tcp.flags.ack == 1 && tcp.dstport == 443 && ip.id >= 0"),
    (
        "ack-to-https",
        "tcp.flags.ack == 1 && tcp.dstport == 443"
        " && !(ip.src == 198.51.100.254)",
    ),
    (
        "dns-a-queries",
        "dns.flags.response == 0 && dns.qry.type == 1 && !dns.response_to",
    ),
    ("ack-outside-testnet", "tcp.flags.ack == 1 && ip.src == 198.51.100.0/24"),
    ("tcp-source-testnet", "tcp && tcp.srcport >= 41000"),
)


def _catalog_coverage(path: Path) -> dict[str, object]:
    """Counts the catalog's frame-number and time fields each variant flags."""
    with closing(
        sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True
        )
    ) as database:
        records = [
            str(row[0])
            for row in database.execute("SELECT record FROM fields_records")
        ]
    typed = {
        field.abbreviation: field.tshark_type
        for field in parse_tshark_fields(records)
        if field.tshark_type in POSITION_TYPES
    }
    caught = {"full": 0, "simplified": 0}
    missed: list[str] = []
    for name, tshark_type in sorted(typed.items()):
        found = references(name)
        if find_shortcuts(found, "", {name: str(tshark_type)}):
            caught["full"] += 1
        if find_shortcuts(found, "", {}):
            caught["simplified"] += 1
        elif name.split(".")[0] in {"tcp", "udp", "ip", "dns", "eth"}:
            missed.append(name)
    return {
        "position_typed_fields": len(typed),
        "caught": caught,
        "simplified_misses_in_recipe_protocols": missed,
    }


def _verdict(exact: bool, hits: bool) -> str:
    if not exact:
        return "silent_wrong"
    return "shortcut" if hits else "strong_exact"


def _witness_rows(
    cases: dict[str, ModelSemanticCase], artifacts: ModelSplitArtifacts
) -> list[dict[str, object]]:
    """Runs every witness on its case's probes and scores both variants."""
    probes = {probe.probe_id: probe for probe in artifacts.probes}
    first_request = {
        case.case_id: case.paraphrases[0] for case in cases.values()
    }
    runner = TsharkRunner()
    rows: list[dict[str, object]] = []
    for case_id, display_filter in _WITNESSES:
        case = cases[case_id]
        exact = all(
            runner.run(probes[probe_id].capture_path, display_filter).frames
            == case.labels(probes[probe_id])
            for probe_id in _SPLIT_PROBES[case.split]
        )
        found = references(display_filter)
        full = find_shortcuts(
            found, first_request[case_id], tshark_types(found.fields)
        )
        simplified = find_shortcuts(found, first_request[case_id], {})
        rows.append(
            {
                "case_id": case_id,
                "filter": display_filter,
                "probe_exact": exact,
                "full": _verdict(exact, bool(full)),
                "simplified": _verdict(exact, bool(simplified)),
                "full_hits": [hit.model_dump(mode="json") for hit in full],
            }
        )
    return rows


def _gold_candidates(
    cases: Sequence[ModelSemanticCase],
) -> list[tuple[str, IntentIrV1 | str]]:
    """Every gold filter, target and single-site mutant with its request."""
    found: list[tuple[str, IntentIrV1 | str]] = []
    for case in cases:
        request = " ".join(case.paraphrases)
        found += [
            (request, case.reference_filter),
            (request, case.mutation_filter),
            (request, case.canonical_ir),
        ]
        found += [
            (request, compile_intent(mutant.intent))
            for mutant in single_site_mutants(case.canonical_ir)
        ]
    return found


def _committed_answers(
    results: Path, requests: dict[str, str]
) -> list[tuple[str, IntentIrV1 | str]]:
    """Every executed answer of every committed scored run."""
    found: list[tuple[str, IntentIrV1 | str]] = []
    for outcomes in sorted(results.glob("*/scored/outcomes.jsonl")):
        for line in outcomes.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if item["disjunctions"] is None:
                continue
            if item["candidate_filter"] is not None:
                candidate: IntentIrV1 | str = item["candidate_filter"]
            else:
                intent = (
                    outcomes.parent
                    / "intents"
                    / item["condition"]
                    / f"{item['item_id']}.json"
                )
                candidate = IntentIrV1.model_validate_json(
                    intent.read_text(encoding="utf-8")
                )
            found.append((requests[item["item_id"]], candidate))
    return found


def _false_positives(
    candidates: Sequence[tuple[str, IntentIrV1 | str]],
) -> dict[str, object]:
    """Counts flagged candidates and times each variant's check."""
    flagged = {"full": 0, "simplified": 0}
    timings: dict[str, list[float]] = {"full": [], "simplified": []}
    for request, candidate in candidates:
        started = perf_counter()
        found = references(candidate)
        full = find_shortcuts(found, request, tshark_types(found.fields))
        timings["full"].append((perf_counter() - started) * 1000)
        started = perf_counter()
        simplified = find_shortcuts(references(candidate), request, {})
        timings["simplified"].append((perf_counter() - started) * 1000)
        flagged["full"] += bool(full)
        flagged["simplified"] += bool(simplified)
    return {
        "candidates": len(candidates),
        "flagged": flagged,
        "median_ms": {
            name: round(statistics.median(values), 3)
            for name, values in timings.items()
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Measures both variants once and writes the receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    arguments = parser.parse_args(argv)
    cases = model_semantic_cases()
    with TemporaryDirectory(prefix="dfilterforge-shortcut-") as work:
        artifacts = generate_model_split(Path(work))
        requests = {item.item_id: item.intent for item in artifacts.inputs}
        witnesses = _witness_rows(
            {case.case_id: case for case in cases}, artifacts
        )
    receipt = {
        "schema_version": _SCHEMA_VERSION,
        "source_revision": arguments.source_revision,
        "tshark_version": TsharkRunner().version(),
        "catalog_sha256": file_sha256(DEFAULT_CATALOG_PATH),
        "shortcuts_sha256": file_sha256(
            Path(__file__).parents[1] / "src" / "dfilterforge" / "shortcuts.py"
        ),
        "catalog": _catalog_coverage(DEFAULT_CATALOG_PATH),
        "witnesses": witnesses,
        "gold": _false_positives(_gold_candidates(cases)),
        "committed_answers": _false_positives(
            _committed_answers(arguments.results_dir, requests)
        ),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
