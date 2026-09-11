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
replay, and measured receipts. The Web Evaluation Lab still uses recorded
data. See `docs/progress.md` for verified results and the remaining pilot
gates.

## Development

The reproducible entry point is Docker Compose:

```text
docker compose --profile pilot run --rm lab doctor
docker compose --profile dev build test
docker compose --profile dev run --rm test
docker compose --profile web-local up --build
```

The Docker daemon must be running in Linux container mode. Host Python and
tshark installations are not part of the supported execution environment.

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
specification, candidate IR, and curated capture root, then re-executes the
reference, candidate, and any needed predicate filters. Its replay decision
uses exact frame tuples and ignores runtime and stored hash claims.

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
Go/No-Go decision. The Web remains recorded-only until that decision passes.

## Safety boundary

The public demo accepts only repository-curated captures. Do not expose tshark
or arbitrary capture upload directly to the public internet.
