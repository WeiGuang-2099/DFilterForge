# DFilterForge

Execution-grounded natural-language synthesis for Wireshark display filters.

DFilterForge compiles a typed packet intent into a Wireshark display filter,
validates it against a versioned field catalog, and compares candidate and
reference behavior across multiple probe captures. Results are described as
empirical observations under a pinned environment, never as global semantic
proof.

## Current status

The local CLI connects the typed compiler to a bounded tshark 4.6.8 runner,
synthetic multi-probe captures, packet diffs, and measured receipts. The Web
Evaluation Lab still uses recorded data. See `docs/progress.md` for verified
results and the remaining pilot gates.

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
docker compose --profile pilot run --rm lab replay-run --receipt /workspace/artifacts/pilot/syn.receipt.json
```

Replace the task ID to run the DNS and UDP cases. `evaluate-live` executes
both reference and candidate filters and rejects a reference that disagrees
with the independent labels. Candidate differences remain visible in the
receipt. Its environment sidecar records measured binary and runner identity;
it explicitly lists unmeasured container and shared-library properties.
The summary includes a packet-set hash that excludes runtime measurements.
`replay-run` validates receipt structure and metrics; it does not re-execute
tshark. Pass `--environment-hash` to check against a known environment hash.

The runner snapshots at most 16 MiB per capture, allows at most five seconds
per tshark process, limits output and frame count, and kills the process group
on completion or failure. Display filters are passed as a single argument with
`shell=False`. These limits complement the container resource restrictions.

## Safety boundary

The public demo accepts only repository-curated captures. Do not expose tshark
or arbitrary capture upload directly to the public internet.
