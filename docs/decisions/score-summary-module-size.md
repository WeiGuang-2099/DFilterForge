# Score summary: two modules, aggregation and report

The repository keeps modules under about 500 lines. The scored-run summary is the one
place that guidance could not hold: the eight published contracts are fixed by the
protocol, and so is every column of the report built from them. This records why the
summary is two modules rather than one, and what the split costs, so the size is a
decision with a measurement behind it rather than a followup bullet nobody reads.

An earlier version of this record argued the opposite, on the grounds that a sibling
renderer could not re-export `render_markdown` without an import cycle. That is still
true of a re-export. The name was moved instead.

## Question

Should the pure aggregation and the Markdown renderer built on it be one module or two,
and if two, where does the public name `render_markdown` live?

## Measured

```text
wc -l src/dfilterforge/*.py | sort -rn | sed -n '2,9p'
    797 src/dfilterforge/score_summary.py
    775 src/dfilterforge/run_store.py
    744 src/dfilterforge/model_split.py
    644 src/dfilterforge/benchmark.py
    527 src/dfilterforge/cli.py
    526 src/dfilterforge/scoring.py
    522 src/dfilterforge/generation.py
    503 src/dfilterforge/live.py
```

`score_summary.py` is 797 lines, of which 107 are blank and 176 are docstrings.
`score_report.py` is 351, of which 36 are blank and 51 are docstrings. The eight
published contracts (`OutcomeV1`, `ItemOutcomeV1`, `RateV1`, `UsageV1`, `RecallV1`,
`ConditionSummaryV1`, `ComparisonV1` and `ScoreSummaryV1`) plus the two provenance
contracts (`EffectiveSettingsV1` and `SpendV1`) take 232 lines of class body between
them, every field of them named by the protocol; the rest of `score_summary.py` is the
aggregation and the seeded bootstrap.

The two files hold 1,148 lines between them. Merged back into one module, minus the
28-line docstring and import header the split introduced, that is 1,120 lines, and pylint
refuses the file at its `max-module-lines` ceiling of 1,000:

```text
pylint --disable=all --enable=C0302 <the merged module>
C0302: Too many lines in module (1120/1000) (too-many-lines)
```

## Decision

Two modules. `score_summary.py` holds the constants, the published contracts and the
aggregation; `score_report.py` holds the Markdown renderer, imports `score_summary` and
is never imported by it. The size gate decided it: a single module carrying both is a
pylint error, not a style preference, and the report grew again when the run-settings and
spend sections were added.

`render_markdown` moved rather than being re-exported, which is what makes the split
cycle-free. A re-export would have made `score_summary` import its own sibling back, so
importing the sibling first would fail. The cost is that the public name changed address:
every caller now imports it from `dfilterforge.score_report`. Today those callers are
`run_store.py` and `tests/test_score_summary.py`, and any later step that renders a
summary imports it from there too.

The split preserves the two properties that are worth more than either line count.
Neither module imports anything that executes or reads disk, so every metric and every
rendered line is testable on a host with no tshark and no network, which the import
contract enforces for both modules by name. `render_markdown` reads a `ScoreSummaryV1`
and nothing else, so `candidate_filter`, the one field that can hold model text, is
structurally unreachable from the published report rather than filtered out of it.

## Revisit when

- The aggregation half alone passes 500 lines of code that is not a published contract.
- A second renderer is added (HTML, or a per-condition detail table). A third module for
  the shared constants pays for itself only then.
- A metric is added whose definition is not a rate over cases, which would break the
  `_rate` and `_ratio_rate` pair the aggregation is built around.

## Reproduce

```text
uv run --frozen --no-sync python -c "import io,pathlib,tokenize;[print(p.name,len(s.splitlines()),sum(1 for x in s.splitlines() if not x.strip()),sum(t.end[0]-t.start[0]+1 for t in tokenize.generate_tokens(io.StringIO(s).readline) if t.type==tokenize.STRING and t.line.strip()[:3] in ('\"\"\"',\"'''\"))) for p in sorted(pathlib.Path('src/dfilterforge').glob('score_*.py')) for s in [p.read_text(encoding='utf-8')]]"
# prints: score_report.py 351 36 51
#         score_summary.py 797 107 176
```
