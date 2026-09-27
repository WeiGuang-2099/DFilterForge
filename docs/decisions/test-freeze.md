# Test freeze

## Question

What must hold before the first test request? Until now the only guard was
`PrepareManifestV1.split: Literal["dev"]`.

## Decision

- `prepare --split test` builds the 112 test items on the dev code path.
- `src/dfilterforge/held_out_freeze.json` holds the frozen test prepare
  manifest, digests of the test inputs, gold with item routing, gold hash,
  captures and feedback labels that CI recomputes, and `admitted_prepares`,
  the SHA-256 of every `prepare.json` a test call may answer, frozen first.
- The call refuses a test prepare the record does not admit before any client
  exists. `dfilterforge.held_out` is not prepare-hashed and an import contract
  keeps it from gold, so admitting a later prepare is a commit to the record.
- 12 files are prepare-hashed (8 before): the script, the case tables and
  the request builders' import closure, which stops at `completions.py`
  (request settings, recorded whole by each run manifest) and `errors.py`.
  Publish follows the prepare's conditions; scoring keeps every pass over a
  manifest-less tree on dev.

## Before and after

Before is ea4656f; no refusal sends a request or creates a run.

| Case | Before | After |
| --- | --- | --- |
| dev `prepare.json` edited to say test | `prepare_invalid` | `freeze_record_missing`, or `test_not_frozen` once a record exists |
| a second `prepare --split test`, identical prompts | cannot be prepared | `test_not_frozen` |
| record not JSON, not the schema or over 1 MiB | none | `freeze_record_invalid` |
| a prepare admitted after the frozen one | none | 448 requests sent |
| edit to canonical, field_catalog, text_limits or model_client after prepare | call proceeds | `prepare_code_mismatch` |
| C4-only run | `run_layout_invalid` at publish | published, 40 items scored |
| C4-only run over a full frozen prompt set | not reachable | `prepared_drift` |
| stored test answers, no manifest | 112 scored, 56 test specs written | `split_violation` |
| test case, routing or capture edited after the freeze | not caught | CI fails |

Lab service (1 CPU, 512 MB) at e37a7a7: reference control 147 s (320 strong
exact, 128 abstained), mutation 82 s (160 silent-wrong, 64 false-ready),
`--check` as long, peak 125 MiB. Test image: test prepare 9 s, suite +30 tests.

## Freeze procedure

```text
export MSYS_NO_PATHCONV=1  # Git Bash at the repo root, clean tree at the last code commit
W=$(pwd -W) REV=$(git rev-parse --short HEAD) D=$(date -u +%F) K=/opt/dfilterforge/catalog.sqlite3 M=/workspace/artifacts/model-eval
T="docker compose --profile dev run --rm --volume $W/artifacts:/workspace/artifacts --volume $W/docs/results:/workspace/results:ro test python"
docker compose --profile dev build test; docker compose --profile pilot build lab
the CI re-score loop with --check: every committed output must reproduce
$T scripts/probe_adequacy.py --output /workspace/artifacts/test-freeze-gate.json --source-revision $REV
$T scripts/model_run.py prepare --catalog $K --output-dir $M/dev-qwen3-32b-$D --source-revision $REV
$T scripts/model_run.py prepare --split test --catalog $K --output-dir $M/test-qwen3-32b-$D --source-revision $REV
copy prepare.json and prepared/ of both to docs/results/, then for each and C in reference mutation:
docker compose --profile pilot run --rm lab score --run-dir /workspace/results/RUN --control C --code-revision $REV
$T -m dfilterforge.held_out_digests --prepare-dir /workspace/results/test-qwen3-32b-$D --output /workspace/artifacts/held_out_freeze.json
```

Copy the record beside `held_out.py`, set `_FROZEN = True` in its test, quote
the printed prefixes in `docs/protocol.md`, keep the receipt as
`evidence/test-freeze-gate.json`. Pass A publishes into the committed tree.

## Week 3 and corrections

- A repair round's prompt set is admitted by appending its `prepare.json`
  digest to `admitted_prepares` in its own commit, before its first request.
- A run over some conditions, such as the dev C2 and C4 ceiling, answers a
  copy of a prepare directory cut to them; call, publish and scoring follow.
- A test gold or scorer correction after the freeze copies each test run's
  `scored/` outcomes and summaries to `scored-original/`, which CI does not
  re-score, then re-scores in place; a gold correction also rewrites the
  record's `digests`, naming the old values in its commit.

## Limits

No code checks settings, pass timing or which runs exist; the protocol states
them and run manifests record them. A call refuses a hashed-file edit made
after its prepare (`prepare_code_mismatch`) before any request. The
frozen-prompt test also fails on it, on a host and in the CI step that runs it
with `docs/` mounted, but only while a prompt set under `docs/results` has no
`run_manifest.json` beside it: once pass A publishes into the committed test
directory, pass B and the slot winners' test passes, which call from the same
prepare under their own run ids, are guarded by the call alone, as is any
prepare directory outside `docs/results`. The call reads the working-tree
record and does not check that it is committed, and it trusts the split a
prompt set declares: a test prompt set hand-edited to say dev is sent, and
only the scorer refuses its answers.
