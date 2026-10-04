"""One-off: measures counterexample cards with and without header facts.

Ablation 008. Runs in the test image with the src tree of the Full revision
mounted, or for Simplified the same tree with
008-counterexample-facts-simplified.patch applied. The committed results tree
is mounted read-only. Writes one JSON receipt.

Measured for the loaded variant:
- facts: per feedback probe, the frames whose shown header values tshark
  confirmed, the tshark runs and the wall time it took;
- label determination: per ready case, whether the entry the card would show
  for a frame, without its number and verdicts and with every port from
  41000 to 51254 read as one value, determines the frame's feedback label;
  Full also reports two context keys: addresses masked, and the design's
  scratch key of layers, TCP flags and DNS response bit;
- cards: for each authored mutation and each killed single-site mutant, the
  card kind, frames and bytes, the leak checks of tests/test_counterexample.py
  and the wall time of building them, repeated;
- plans: the repair plan of each counted 2026-09-26 dev pass;
- lines: the module's physical, nonblank and code lines and public names.
"""

import argparse
import ast
from collections import Counter
from collections import defaultdict
import hashlib
import io
import json
from pathlib import Path
import statistics
from tempfile import TemporaryDirectory
import time
import tokenize

from dfilterforge import counterexample
from dfilterforge.benchmark import RECIPES
from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import content_sha256
from dfilterforge.canonical import file_sha256
from dfilterforge.catalog_runtime import bind_catalog
from dfilterforge.compiler import compile_intent
from dfilterforge.evaluation import evaluate_probe
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import walk_predicates
from dfilterforge.live import measure_environment
from dfilterforge.model_feedback import feedback_labels_sha256
from dfilterforge.model_feedback import generate_feedback_probes
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import MUTANT_WAIVERS
from dfilterforge.mutants import single_site_mutants
from dfilterforge.repair import build_plan
from dfilterforge.repair import plan_bytes
from dfilterforge.runner import TsharkRunner
from dfilterforge.witnesses import WITNESS_NAMES

DEV_BASES = (
    "dev-qwen3.5-9b-2026-09-26",
    "dev-qwen3.5-122b-a10b-2026-09-26",
    "dev-deepseek-v4-pro-0813-2026-09-26",
    "dev-qwen3-32b-2026-09-26",
)
EPHEMERAL = range(41000, 51255)
PORT_FIELDS = ("tcp.srcport", "tcp.dstport", "udp.srcport", "udp.dstport")
VERDICT_KEYS = {"frame", "answer_matched", "should_match"}
ADDRESS_FIELDS = ("ip.src", "ip.dst")
FULL = hasattr(counterexample, "read_frame_facts")


class CountingRunner(TsharkRunner):
    """The bounded runner, counting the filters it runs."""

    def __init__(self) -> None:
        super().__init__()
        self.runs = 0

    def run(self, capture, display_filter):
        self.runs += 1
        return super().run(capture, display_filter)


def one_frame_card(probe_id, labels, frame, facts):
    """The card the variant shows when only ``frame`` disagrees."""
    probe = evaluate_probe(
        probe_id, tuple(sorted(labels)), tuple(sorted(labels ^ {frame})), 0.0
    )
    if FULL:
        return counterexample.frames_card(probe, facts)
    return counterexample.frames_card(probe)


def shown_entry(card):
    """A card frame's shown values, ephemeral ports read as one value."""
    (fact,) = card.frames
    values = fact.model_dump(mode="json", by_alias=True, exclude_none=True)
    for name in PORT_FIELDS:
        if isinstance(values.get(name), int) and values[name] in EPHEMERAL:
            values[name] = "ephemeral"
    return {
        key: value for key, value in values.items() if key not in VERDICT_KEYS
    }


def without_addresses(entry):
    """Context: the shown entry with both addresses masked."""
    return {
        key: value for key, value in entry.items() if key not in ADDRESS_FIELDS
    }


def layers_flags_response(entry):
    """Context: the design's scratch key, called membership facts there.

    Which of TCP, UDP and DNS the frame carries, its TCP flag names and its
    DNS response bit.
    """
    return {
        "tcp": "tcp.srcport" in entry,
        "udp": "udp.srcport" in entry,
        "dns": "dns.flags.response" in entry,
        "tcp.flags": entry.get("tcp.flags"),
        "dns.flags.response": entry.get("dns.flags.response"),
    }


def label_determination(feedback, facts_by_probe):
    """Counts the cases whose labels the shown entries determine."""
    variants = {"shown": lambda entry: entry}
    if FULL:
        variants["context_without_addresses"] = without_addresses
        variants["context_layers_flags_response"] = layers_flags_response
    report = {}
    for name, view in variants.items():
        determined = Counter()
        cases = Counter()
        undetermined = []
        for case_id, spec in feedback.specs.items():
            (expected,) = spec.probes
            labels = set(expected.expected_frames)
            facts = facts_by_probe.get(expected.probe_id)
            frames = range(1, frame_count(feedback, expected.probe_id) + 1)
            groups = defaultdict(set)
            for frame in frames:
                card = one_frame_card(expected.probe_id, labels, frame, facts)
                groups[canonical_json(view(shown_entry(card)))].add(
                    frame in labels
                )
            cases[spec.split] += 1
            if all(len(group) == 1 for group in groups.values()):
                determined[spec.split] += 1
            else:
                undetermined.append(case_id)
        report[name] = {
            "determined": dict(sorted(determined.items())),
            "cases": dict(sorted(cases.items())),
            "determined_total": sum(determined.values()),
            "cases_total": sum(cases.values()),
            "undetermined_cases": undetermined,
        }
    return report


def frame_count(feedback, probe_id):
    (probe,) = [
        probe for probe in feedback.probes if probe.probe_id == probe_id
    ]
    return len(probe.recipes)


def candidate_text(candidate):
    if isinstance(candidate, str):
        return candidate
    return canonical_json(candidate.model_dump(mode="json"))


def candidates(split):
    """The authored mutation and every killed mutant of each ready case."""
    waived = {(waiver.case_id, waiver.edit) for waiver in MUTANT_WAIVERS}
    rows = []
    for case in split.gold.cases:
        rows.append((case, case.mutation_filter))
        rows.extend(
            (case, mutant.intent)
            for mutant in single_site_mutants(case.spec.canonical_ir)
            if (case.case_id, mutant.edit) not in waived
        )
    return rows


def gold_texts(case, runner):
    """The gold filters a card must never contain, in both spellings."""
    canonical = case.spec.canonical_ir
    leaves = [
        IntentIrV1(expression=predicate)
        for _, predicate in walk_predicates(canonical.expression)
        if predicate.operator is not Operator.EXISTS
    ]
    catalog = bind_catalog(runner, (canonical,))
    return {
        case.spec.reference_filter,
        *(compile_intent(ir) for ir in (canonical, *leaves)),
        *(compile_intent(ir, catalog) for ir in (canonical, *leaves)),
    }


def percentile(values, share):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def build_cards(feedback, rows, runner):
    """Builds every card once; returns texts, facts and timings."""
    builder = counterexample.CardBuilder(feedback, runner)
    facts_by_probe = {}
    facts_report = {}
    if FULL:
        first = {}
        for spec in feedback.specs.values():
            first.setdefault(spec.probes[0].probe_id, spec.probes[0])
        for probe_id, expected in first.items():
            before = runner.runs
            start = time.perf_counter()
            facts = builder.facts(expected)
            seconds = time.perf_counter() - start
            facts_by_probe[probe_id] = facts
            facts_report[probe_id] = {
                "frames": frame_count(feedback, probe_id),
                "frames_confirmed": len(facts),
                "shown_values_confirmed": sum(
                    len(fact.model_dump(exclude_none=True))
                    for fact in facts.values()
                ),
                "tshark_runs": runner.runs - before,
                "seconds": round(seconds, 3),
            }
    cards = []
    per_card = []
    before = runner.runs
    start = time.perf_counter()
    for case, candidate in rows:
        begin = time.perf_counter()
        card = builder.card(case.case_id, candidate)
        per_card.append(time.perf_counter() - begin)
        cards.append(card)
    total = time.perf_counter() - start
    timing = {
        "cards_seconds": round(total, 3),
        "card_ms_p50": round(1000 * statistics.median(per_card), 2),
        "card_ms_p95": round(1000 * percentile(per_card, 0.95), 2),
        "card_tshark_runs": runner.runs - before,
        "facts_seconds": round(
            sum(entry["seconds"] for entry in facts_report.values()), 3
        ),
    }
    timing["total_seconds"] = round(
        timing["cards_seconds"] + timing["facts_seconds"], 3
    )
    return builder, cards, facts_by_probe, facts_report, timing


def card_stats(texts_and_cards):
    kinds = Counter()
    frames = Counter()
    sizes = []
    for text, card in texts_and_cards:
        if card is None:
            kinds["none"] += 1
            continue
        if isinstance(card, counterexample.FramesCardV1):
            kinds["frames"] += 1
            frames[len(card.frames)] += 1
        else:
            kinds["error"] += 1
        sizes.append(len(text.encode("utf-8")))
    stats = {
        "kinds": dict(sorted(kinds.items())),
        "frames_per_card": {str(k): v for k, v in sorted(frames.items())},
    }
    if sizes:
        stats["bytes"] = {
            "min": min(sizes),
            "p50": statistics.median(sizes),
            "mean": round(statistics.fmean(sizes), 1),
            "p95": percentile(sizes, 0.95),
            "max": max(sizes),
            "total": sum(sizes),
        }
    return stats


def leak_checks(split, feedback, rows, cards, builder, runner):
    """The leak checks of tests/test_counterexample.py, counted."""
    items = defaultdict(set)
    for item_id, case_id in split.gold.item_to_case.items():
        items[case_id].add(item_id)
    names = {*RECIPES, *WITNESS_NAMES}
    captures = {probe.probe_id: probe.capture_path for probe in feedback.probes}
    failures = Counter()
    forbidden_by_case = {}
    for (case, candidate), card in zip(rows, cards, strict=True):
        (expected,) = feedback.specs[case.case_id].probes
        if case.case_id not in forbidden_by_case:
            forbidden_by_case[case.case_id] = {
                case.case_id,
                *items[case.case_id],
                expected.probe_id,
                *(probe.probe_id for probe in case.spec.probes),
                *names,
                *gold_texts(case, runner),
            }
        if not isinstance(card, counterexample.FramesCardV1):
            failures["not_a_frames_card"] += 1
            continue
        text = counterexample.card_json(card)
        if len(text.encode("utf-8")) > counterexample.CARD_MAX_BYTES:
            failures["over_cap"] += 1
        if any(value in text for value in forbidden_by_case[case.case_id]):
            failures["gold_or_name_in_card"] += 1
        display = (
            candidate
            if isinstance(candidate, str)
            else compile_intent(candidate, bind_catalog(runner, (candidate,)))
        )
        selected = runner.run(captures[expected.probe_id], display).frames
        for fact in card.frames:
            if fact.should_match != (fact.frame in expected.expected_frames):
                failures["should_match_wrong"] += 1
            if fact.answer_matched != (fact.frame in selected):
                failures["answer_matched_wrong"] += 1
    canonical_cards = sum(
        builder.card(case.case_id, case.spec.canonical_ir) is not None
        for case in split.gold.cases
    )
    return {
        "candidates_checked": len(rows),
        "failures": dict(sorted(failures.items())),
        "canonical_ir_cards": canonical_cards,
    }


def plans(results, runner):
    report = {}
    for base in DEV_BASES:
        start = time.perf_counter()
        plan = build_plan(results / base, runner=runner)
        seconds = time.perf_counter() - start
        payload = plan_bytes(plan)
        kinds = Counter(item.card_kind for item in plan.items)
        outcomes = Counter(item.base_outcome for item in plan.items)
        frames = Counter(
            len(json.loads(item.card)["frames"])
            for item in plan.items
            if item.card_kind == "frames"
        )
        sizes = [
            len(item.card.encode("utf-8"))
            for item in plan.items
            if item.card is not None
        ]
        report[base] = {
            "items": len(plan.items),
            "base_outcomes": dict(sorted(outcomes.items())),
            "card_kinds": dict(sorted(kinds.items())),
            "frames_per_card": {str(k): v for k, v in sorted(frames.items())},
            "card_bytes": sorted(sizes),
            "plan_sha256": hashlib.sha256(payload).hexdigest(),
            "plan_bytes": len(payload),
            "seconds": round(seconds, 3),
        }
    return report


def line_counts(path):
    """Physical, nonblank and code lines, and the public names."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    tree = ast.parse(text)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(
            node,
            (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstrings.update(range(first.lineno, first.end_lineno + 1))
    skipped = {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
        tokenize.ENCODING,
    }
    code = set()
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type in skipped:
            continue
        for line in range(token.start[0], token.end[0] + 1):
            if line not in docstrings:
                code.add(line)
    public = []
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            public.append(node.name)
        elif isinstance(node, ast.Assign):
            public.extend(
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(
            node.target, ast.Name
        ):
            public.append(node.target.id)
    public = sorted(name for name in public if not name.startswith("_"))
    return {
        "physical": len(lines),
        "nonblank": sum(1 for line in lines if line.strip()),
        "code": len(code),
        "public_names": public,
        "public_name_count": len(public),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=("full", "simplified"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--results", type=Path, default=Path("/results"))
    args = parser.parse_args()
    if args.variant != ("full" if FULL else "simplified"):
        raise SystemExit("the loaded module is not the named variant")
    runner = CountingRunner()
    environment = measure_environment(runner)
    module_path = Path(counterexample.__file__)
    started = time.perf_counter()
    with TemporaryDirectory() as staging:
        split = generate_model_split(Path(staging))
        feedback = generate_feedback_probes(split)
        gold_sha256 = file_sha256(split.gold_path)
        # As repair.build_plan does: no card may read a scored probe.
        for capture in split.capture_paths:
            capture.unlink()
        rows = candidates(split)
        identity = {
            "environment_hash": environment.environment_hash(),
            "tshark_version": environment.tshark_version,
            "gold_file_sha256": gold_sha256,
            "feedback_captures": {
                probe.probe_id: file_sha256(probe.capture_path)
                for probe in feedback.probes
            },
            "feedback_labels_sha256": {
                split_name: feedback_labels_sha256(feedback, split_name)
                for split_name in ("dev", "test")
            },
            "candidates": len(rows),
            "candidates_sha256": content_sha256(
                [[case.case_id, candidate_text(c)] for case, c in rows]
            ),
            "dev_base_manifests": {
                base: file_sha256(args.results / base / "run_manifest.json")
                for base in DEV_BASES
            },
            "repetitions": args.repetitions,
        }
        repetitions = []
        texts = None
        for _ in range(args.repetitions):
            builder, cards, facts_by_probe, facts_report, timing = build_cards(
                feedback, rows, runner
            )
            rep_texts = [
                None if card is None else counterexample.card_json(card)
                for card in cards
            ]
            timing["cards_sha256"] = content_sha256(rep_texts)
            repetitions.append(timing)
            if texts is None:
                texts = rep_texts
                first = (builder, cards, facts_by_probe, facts_report)
            elif rep_texts != texts:
                raise SystemExit("cards differ between repetitions")
        builder, cards, facts_by_probe, facts_report = first
        determination = label_determination(feedback, facts_by_probe)
        leaks = leak_checks(split, feedback, rows, cards, builder, runner)
        stats = card_stats(zip(texts, cards, strict=True))
        by_split = {}
        for split_name in ("dev", "test"):
            chosen = [
                (text, card)
                for (case, _), text, card in zip(
                    rows, texts, cards, strict=True
                )
                if case.spec.split == split_name
            ]
            by_split[split_name] = card_stats(chosen)
    plan_report = plans(args.results, runner)
    receipt = {
        "schema_version": "ablation-008/1.0",
        "variant": args.variant,
        "source_revision": args.source_revision,
        "module_sha256": file_sha256(module_path),
        "measurement_identity": identity,
        "measurement_identity_sha256": content_sha256(identity),
        "facts": facts_report if FULL else None,
        "label_determination": determination,
        "cards": {"all": stats, **by_split},
        "cards_sha256": content_sha256(texts),
        "leak_checks": leaks,
        "plans": plan_report,
        "lines": line_counts(module_path),
        "runtime": {
            "repetitions": repetitions,
            "median_total_seconds": statistics.median(
                rep["total_seconds"] for rep in repetitions
            ),
            "median_facts_seconds": statistics.median(
                rep["facts_seconds"] for rep in repetitions
            ),
            "median_cards_seconds": statistics.median(
                rep["cards_seconds"] for rep in repetitions
            ),
            "script_seconds": round(time.perf_counter() - started, 3),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
