# Offline scoring: stored answers to one outcome each, without a key

## Problem

At 1c64140 none of the 64 planned dev completions could be scored, and no
command read a completion batch. `evaluate_live` took only an `IntentIrV1`
(live.py:420), so a raw display filter had no execution path; a filter tshark
rejected raised instead of being classified; the runner reported unknown
fields, type errors and syntax errors alike as `tshark_failed`.

## Change

- `dfilterforge score` runs in the no-network lab image. It regenerates the
  split in a temporary directory, rebuilds each committed prompt from the
  regenerated intent and its recorded field list, requires an exact match
  (retrieval itself is pinned only by the `prepare.json` hashes), and gives
  every item one of the six outcomes.
- Exit status is classified: exit 4 is `filter_rejected`, or
  `filter_unknown_field` when tshark's own first stderr line says so; exit 3
  or 14 is `capture_unreadable`; any other failure stays `tshark_failed`.
- Compile validity is tshark acceptance. A display filter (C1, C2) reaches
  pinned tshark unchanged and is not bound to the catalog, so an accepted name
  outside it (`ssl`) is scored, not rejected; a typed IR (C3, C4) still binds
  the catalog and checks types, operators and values.
- Only an allowlisted code is charged to the candidate: unknown_field,
  ambiguous_field, unsupported_type, unsupported_operator, type_mismatch,
  invalid_value, filter_invalid, filter_too_large, filter_rejected,
  filter_unknown_field, and a timeout, output_limit or frame_limit only when
  the same gold case reruns clean. Any other error stops scoring.
- Gold preflight: each selected reference filter and canonical IR must match
  its labels before any answer is read, so no gold defect is charged to a model.
- The bootstrap draws 1,000 case-level resamples (seed 17) shared by every
  metric; intervals are the nearest-rank 2.5 and 97.5 percentiles.
- `--check` re-executes and compares without writing: `outcomes.jsonl` per
  item and byte for byte, `summary.json`, `summary.md`, and every `*.json`
  under `intents/`, `specs/` and `receipts/`, except each receipt's
  `created_at`, `code_revision`, `p50_runtime_ms`, `p95_runtime_ms` and probe
  `runtime_ms`. Nothing else is compared: not `score_manifest.json` (when and
  at which revision scoring ran), and no other file, even in those trees.
- `--control reference` answers each committed prompt from gold and
  `--control mutation` answers the display-filter prompts with the case's
  authored near-wrong filter; gold holds no typed mutation, so C3 and C4 are
  reported as not measured there. Neither control contacts a provider.

## Evidence

[Reference](../results/dev-qwen3-32b-2026-09-21/control-reference/summary.json)
and [mutation](../results/dev-qwen3-32b-2026-09-21/control-mutation/summary.json)
control scores of the frozen dev prompts; exit-status
[witnesses](../ablations/evidence/001-exit-status-measurements.json), read in
the [ablation 001](../ablations/001-bounded-tshark-runner.md) addendum. The
controls were scored in the test image with the working tree mounted
read-only, under the lab service's hardening (no network, read-only root, one
CPU, 512 MB, uid 10001), because building the lab image needs a network; CI
runs the `--check` line in the lab service. The last line prints 0: the
1c64140 CLI has no `score` subcommand.

```text
docker compose --profile pilot run --rm lab score --run-dir /workspace/results/dev-qwen3-32b-2026-09-21 --control reference --code-revision YOUR_REVISION
docker compose --profile pilot run --rm lab score --run-dir /workspace/results/dev-qwen3-32b-2026-09-21 --control mutation --code-revision YOUR_REVISION
docker compose --profile pilot run --rm lab score --run-dir /workspace/results/dev-qwen3-32b-2026-09-21 --control reference --check --code-revision YOUR_REVISION
git show 1c64140:src/dfilterforge/cli.py | grep -c '"score"'
```

## Results

| Measure | 1c64140 | now |
| --- | ---: | ---: |
| dev completions with a scoring path | 0 of 64 | 64 of 64 |
| exit-status witnesses not `tshark_failed` | 0 of 6 | 6 of 6 |
| reference control, strong exact per condition | no scorer | 16 of 16 in C1-C4 |
| mutation control, silent-wrong per condition | no scorer | 16 of 16 in C1, C2 |
| `--check` differences, both controls | no scorer | none |

The first row is read from the 1c64140 source and the check row is what
`--check` prints; no score manifest records a wall time or a tshark call count.

## Limits

- 8 ready dev cases make every interval wide and every comparison inconclusive
  (10-discordant-case rule); false-ready and slot match await non-ready gold.
- Per-item cost comes from token counts and the recorded prices, beside the
  provider-reported charge. `cost_is_lower_bound` marks a condition whose
  usage is missing; `price_derived_is_lower_bound` marks the run's derived
  spend when usage is missing or an item was retried. The controls' cost,
  token and latency columns measure nothing: their answers come from gold.
- C2 and C4 list every gold field for 0.625 of items (mean recall 0.739583)
  and the prompts ask for listed names; read C2-C1 and C4-C3 against that.
- The claim is about tshark 4.6.8 in this image only. A receipt's compared
  `environment_hash` covers tshark's version and executable bytes, the catalog
  and profile hashes, the runner source and limits, Python and the machine. A
  fresh build recompiles tshark and re-freezes the catalog on the unpinned
  `ubuntu:24.04` tag, and the archive and this image already hold different
  catalogs (`ce22f217`, `80dc639b`), so CI's first fresh lab build may flag
  every receipt until the controls are re-scored in that image. A candidate
  timeout depends on host load, so a loaded machine can honestly differ.
- The lab container writes `docs/results/` as uid 10001 through a writable
  bind, which works on Docker Desktop; on a Linux host that directory must be
  writable by that uid. `docs/results/.gitkeep` keeps the bind source present.
