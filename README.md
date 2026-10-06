# DFilterForge

Execution-grounded natural-language synthesis for Wireshark display filters.

DFilterForge compiles a typed packet intent into a Wireshark display filter,
validates it against a versioned field catalog, and compares candidate and
reference behavior across multiple probe captures. Results are described as
empirical observations under a pinned environment, never as global semantic
proof.

## Current status

The local CLI connects the typed compiler to a bounded tshark 4.6.8 runner,
synthetic multi-probe captures, packet diffs, predicate traces, executable
replay, and measured receipts. Four hosted models have been scored on the
frozen test split, and one feedback turn carrying a counterexample repaired
35 of the 75 typed C4 answers to ready gold that their counted passes got
silent-wrong or invalid, against 21 for a bare "your filter was incorrect"
turn and 4 for a resample
([locked test result](docs/results/locked-test-v1.md)); nothing has been
trained. For qwen/qwen3-32b's first two dev runs, on the 8 ready dev cases that
existed then, [what the first run shows and what it does not](docs/decisions/first-dev-run.md)
is written down, including a typed-IR prompt gap that the
[second run](docs/decisions/typed-ir-prompt-v2.md) measured closed. Three of its answers first
passed as strong exact because no probe packet separated them from the gold;
the model split probes now end in witness packets, a mutation-adequacy gate
checks every single-site mutant of the gold from a fixed operator set on them
in CI, and the run was re-scored against the corrected gold. The web site in
`apps/web` is a static export built in Docker from committed results only; it
never calls a model, and CI re-derives every value it shows from the committed
files ([web site](docs/decisions/web-site.md)). See `docs/progress.md` for
verified results and `docs/protocol.md` for the model evaluation protocol. Every committed run and its gold-derived reference and
mutation controls re-score offline in the no-network container.

## Development

The reproducible entry point is Docker Compose:

```text
docker compose --profile pilot run --rm lab doctor
docker compose --profile dev build test
docker compose --profile dev run --rm test
SOURCE_COMMIT=$(git rev-parse HEAD) docker compose --profile web-local up --build
```

The last command serves the site at `http://127.0.0.1:3000/DFilterForge/`;
page links name `SOURCE_COMMIT`, so the build refuses to run without it.

The Docker daemon must be running in Linux container mode. tshark execution,
the catalog freeze and scoring all run in containers. Split generation, field
retrieval and prompt preparation are pure Python and also run on the host with
`uv run --frozen`. The hosted model call must run on the host, because the
lab, test and dev containers all run with `network_mode: none`.

The `Dockerfile` verifies the official Wireshark 4.6.8 source archive against
its published SHA-256 before building a tshark-only runtime. The CLI container
runs without a network, Linux capabilities, or root privileges.

## Three local execution cases

Generate nine deterministic captures using seeds 17, 42, and 2026:

```text
docker compose --profile pilot build lab
docker compose --profile pilot run --rm lab fixtures generate --output-dir /workspace/artifacts/pilot
```

The generated task IDs are `tcp-syn-no-ack`, `dns-udp-query`, and
`udp-destination-53`. Each has independent packet labels and a near-wrong
filter witness. Run a case with the source revision you are evaluating:

```text
docker compose --profile pilot run --rm lab evaluate-live --spec /workspace/artifacts/pilot/specs/tcp-syn-no-ack.json --candidate-ir /workspace/artifacts/pilot/intents/tcp-syn-no-ack.json --capture-root /workspace/artifacts/pilot/captures --run-id syn-example --created-at 2026-09-04T00:00:00Z --code-revision YOUR_REVISION --output /workspace/artifacts/pilot/syn.receipt.json
docker compose --profile pilot run --rm lab replay-run --receipt /workspace/artifacts/pilot/syn.receipt.json --spec /workspace/artifacts/pilot/specs/tcp-syn-no-ack.json --candidate-ir /workspace/artifacts/pilot/intents/tcp-syn-no-ack.json --capture-root /workspace/artifacts/pilot/captures
```

Replace the task ID to run the DNS and UDP cases. `evaluate-live` executes
both reference and candidate filters and rejects a reference that disagrees
with the independent labels. Candidate differences remain visible in the
receipt. Its environment sidecar records measured binary and runner identity;
it explicitly lists unmeasured container and shared-library properties.
The summary includes a packet-set hash that excludes runtime measurements.
For a packet diff, the trace sidecar records actual tshark matches for every
candidate and canonical leaf predicate on counterexample frames. It does not
record packet payloads or inferred field values. `replay-run` requires the
specification, the curated capture root, and either the candidate IR or
`--receipt-filter`, which replays the receipt's own display filter. It
re-executes the reference and the candidate, plus any needed predicate filters
when given an IR. Its replay decision uses exact frame tuples and ignores
runtime and stored hash claims.

The runner snapshots at most 16 MiB per capture, allows at most five seconds
per tshark process, limits output and frame count, and kills the process group
on completion or failure. Display filters are passed as a single argument with
`shell=False`. These limits complement the container resource restrictions.

## Frozen field catalog

The Docker build freezes the complete tshark field and value inventory in
`/opt/dfilterforge/catalog.sqlite3`, including the actual version and isolated
dissector configuration. SQLite is part of Python's standard library. The
compiler reads the fields referenced by an intent from that inventory, keeping
memory bounded without restricting validation to a protocol whitelist.

`compile` and `evaluate-live` validate fields, operators, literal types, and the
catalog's runtime binding before any capture execution. A supplied catalog is
checked against the frozen environment. The domain compiler remains independent
of file storage and subprocess execution.

```text
docker compose --profile pilot run --rm lab catalog freeze --output /workspace/artifacts/catalog.sqlite3
docker compose --profile pilot run --rm lab compile --intent-ir /workspace/artifacts/pilot/intents/tcp-syn-no-ack.json
```

The SQLite catalog is generated inside the pinned image. Rebuilding and
extracting twice in the same environment must produce identical catalog bytes;
this checks reproducibility without adding repeated whole-file work to
compilation.

## Semantic benchmark

The pilot suite contains 36 authored specifications with an independent
semantic review, each with three probes and a near-wrong filter. Packet labels
come from named synthetic packet recipes independently of the IR and
display-filter strings. The suite includes explicit counterexamples for field
absence, direction, Boolean flags, numeric boundaries, DNS, subnets, and nested
logic. Generated manifests record `ready` status, `reviewed` review status, and
the review provenance. These are curated pilot fixtures, not a held-out model
test set.

```text
docker compose --profile dev run --rm --volume "${PWD}/artifacts:/workspace/artifacts" test python scripts/benchmark_gate.py --phase suite --source-revision YOUR_REVISION --output-dir /workspace/artifacts/benchmark
docker compose --profile dev run --rm --volume "${PWD}/artifacts:/workspace/artifacts" test python scripts/benchmark_gate.py --phase stability --source-revision YOUR_REVISION --output-dir /workspace/artifacts/benchmark
```

The stability phase executes all 50 byte-distinct captures against all 150
different filter strings twice (15,000 tshark calls). It compares exact frame
tuples and writes progress after each capture. The extra boundary filters are
runtime stress inputs, not additional authored specifications. Different filter
strings do not imply different semantics.

An interrupted stability run can resume from a matching local checkpoint. Use
`--restart-stability` to discard an existing checkpoint explicitly.

CI runs the semantic oracle and mutation checks. The longer complete stability
matrix is an explicit release measurement. Passing these synthetic gates does
not measure model compile validity, silent-wrong rate, or the complete Pilot
Go/No-Go decision.

## Hosted model run

`RUN` below is `dev-qwen3-32b-v2-2026-09-23`: qwen/qwen3-32b on the dev split
via deepinfra, fallbacks off, with the second typed-IR prompt; the date records
when its prompts were frozen (UTC). Its C1 and C2 prompts are byte-identical to
the first run's, `dev-qwen3-32b-2026-09-21`, which is scored and committed.
The [protocol](docs/protocol.md) defines what is measured.

1. Build the test image the prompts are prepared in.
2. Prepare the prompts. Done for `RUN`: `publish` refuses a new `prepare.json`,
   so restore a lost `artifacts/model-eval/RUN` by copying
   `docs/results/RUN/prepare.json` and `prepared/` into it instead.
3. Set `DFILTERFORGE_MODEL_API_KEY` in your shell only. It is never written to
   a file, and `publish` refuses any file holding it or a token-shaped string.
4. Save the third line below as `artifacts/call-config.json` (ignored) with
   the provider's prices filled in; prices cannot be added after the run.
5. Call on the host. On exit 1, read the printed `stop_reason`. `null`: re-run
   with `--resume`. `fatal_http`: fix the key or credit, then resume. `budget`:
   the 0.25 USD cap cannot cover the next request; the run cannot be published.
   `thinking_not_honoured` (`--gate-first`, on by default) ends the run: move
   `artifacts/model-eval/RUN/runs/RUN` out of `runs/`, change the provider or
   model (a new model needs a new `RUN`) and call again without `--resume`.
6. Publish the run beside the frozen prompts.
7. Score offline in the lab container, then commit `docs/results/RUN`.

```text
docker compose --profile dev build test
docker compose --profile dev run --rm --volume "${PWD}/artifacts:/workspace/artifacts" test python scripts/model_run.py prepare --catalog /opt/dfilterforge/catalog.sqlite3 --output-dir /workspace/artifacts/model-eval/RUN --source-revision YOUR_REVISION
{"endpoint_url": "https://openrouter.ai/api/v1/chat/completions", "settings": {"model_id": "qwen/qwen3-32b", "openrouter": {"provider_order": ["deepinfra"], "allow_fallbacks": false, "reasoning": "enabled_false"}}, "prices": {"usd_per_million_input": INPUT_PRICE, "usd_per_million_output": OUTPUT_PRICE, "source": "PRICE_SOURCE"}}
uv run --frozen python scripts/model_run.py call --prepare-dir artifacts/model-eval/RUN --run-id RUN --config artifacts/call-config.json --max-usd 0.25 --source-revision YOUR_REVISION
uv run --frozen python scripts/model_run.py publish --run-dir artifacts/model-eval/RUN/runs/RUN --output docs/results/RUN
docker compose --profile pilot build lab
docker compose --profile pilot run --rm lab score --run-dir /workspace/results/RUN --code-revision YOUR_REVISION
```

Step 5 is the only command here that needs a key and spends money; every other
command is exercised by the test suite or by CI. The
[reference](docs/results/dev-qwen3-32b-v2-2026-09-23/control-reference/summary.md)
and [mutation](docs/results/dev-qwen3-32b-v2-2026-09-23/control-mutation/summary.md)
control scores are the scorer's measured baseline; the model's numbers are in
`docs/results/RUN/scored/summary.md`, where C2 and C4 also print how often
retrieval listed every gold field. `--check` (plus `--control reference`
or `mutation`) reproduces any of them without a key.

## Safety boundary

The public demo accepts only repository-curated captures. Do not expose tshark
or arbitrary capture upload directly to the public internet.

## License

MIT, see `LICENSE`. The Docker images build tshark from the Wireshark 4.6.8
source archive (GPL-2.0-or-later) and the frozen field catalog is derived from
that build; see `NOTICE`.
