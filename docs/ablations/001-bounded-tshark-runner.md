# Ablation 001: Bounded tshark Execution

Status: keep_protected

Measured: 2026-09-04; addendum measured 2026-09-19

## Hypothesis

A direct, buffered `subprocess.run` call could replace the capture snapshot,
streaming output limits, and process-group lifecycle in the bounded runner
while preserving packet results and safety.

## Frozen inputs

- Base revision: `4228b46b9896b228aece6e28a43f0a60832f1dfd` plus the source
  manifest recorded in `evidence/001-pilot.json`.
- Source manifest SHA-256:
  `8b896bf1ffda3707f761d80446d38ecb701107e7ff40260a319f313f5ff57923`.
- Full runner SHA-256:
  `b1c21445e66bd11c5bc51688ac622037752bde5e60e8a0894237dfc5aae92d93`.
- Simplified function SHA-256:
  `78f54b30cb05ae0aaf4c2e6f32ebd7430b41a122f255636380c88e6f09ea3c65`.
- Experiment script SHA-256:
  `1472dc891b5651282094bf9ccebcbc5ccb202a96f92a408df6c16a218197555b`.
- Measured experiment environment hash:
  `2d19d02bdb49de61bb6384773552031d735f181deef9956f77b869a8aeca56f2`.
- Test image ID:
  `sha256:90043f1363166caf46ce4058ef713cc541d743e49fd46515e01a50ac6f99464e`.
- Production image ID:
  `sha256:b03395d3fed27a8aa9cf4bb29f20513d0965c2a7f98179e2d02b366aaeb56eec`.
- Fixture manifest SHA-256:
  `f274caefb339d330baa48a1f0f115d7b9eaada4398a9cbe96a5c970c692bd602`.
- Seeds: 17, 42, 2026. Three tasks, nine PCAPs, 46 synthetic packets.
- Quality threshold: all independently authored frame sets match; byte limits
  remain enforced. Performance threshold: at most 5% p95 regression.

The environment includes actual tshark executable and runner hashes, policy,
Python, and platform information. It is a scoped measurement, not an OCI or
shared-library attestation. Image IDs above are recorded independently by
Docker. The nine individual capture hashes are in the fixture manifest.

## Full and Simplified

Full uses `TsharkRunner` from `src/dfilterforge/runner.py`: bounded capture
snapshots, fixed argv/environment, separate stdout/stderr limits, deadlines,
strict frame validation, and process-group cleanup.

Simplified is the executable `_simplified_run` function in
`scripts/runner_ablation.py`. It uses the same binary, filter arguments,
environment, and five-second timeout, but passes the original path directly
and buffers all output. It omits streaming caps and group cleanup. This
candidate exists only in the experiment script.

Both variants run compiled, reference, and near-wrong filters on every probe.
After warming both paths, three repetitions alternate which variant runs
first, giving 81 paired measurements. Timings cover the call, including
capture hashing, and exclude the cached version check. The final measurement
ran after builds and quality gates completed, with no other project container
workloads running.

## Commands

Run from the repository root with Docker Desktop in Linux-container mode:

```text
docker compose --profile dev --profile pilot build test lab
docker compose --profile dev run --rm test
docker compose --profile dev run --rm test pyright
docker compose --profile dev run --rm test pylint src
docker compose --profile dev run --rm test pyink --check src tests scripts
docker compose --profile dev run --rm test isort --check-only src tests scripts
docker compose --profile dev run --rm test lint-imports --no-cache
docker compose --profile pilot run --rm lab doctor
docker compose --profile pilot run --rm lab fixtures generate --output-dir /workspace/artifacts/pilot
docker compose --profile dev run --rm --volume "${PWD}/artifacts:/workspace/artifacts" test python scripts/runner_ablation.py --fixtures /workspace/artifacts/pilot --output /workspace/artifacts/runner-ablation.json --code-revision 4228b46+working-tree
docker compose --profile pilot run --rm lab ablation run --manifest /workspace/artifacts/runner-ablation.receipt.json
```

See the README for `evaluate-live` and `replay-run` commands. The three
production cases were each executed twice. Both runs and their environment
sidecars are retained in `evidence/001-receipts/`; their hashes and repeated
packet-set comparisons are in `evidence/001-pilot.json`.

## Results

| Measure | Full | Simplified |
| --- | ---: | ---: |
| Exact authored frame sets | 81/81 | 81/81 |
| Paired packet sets equal | 81/81 | 81/81 |
| Near-wrong samples killed | 27/27 | 27/27 |
| Macro F1 | 1.0 | 1.0 |
| Median call latency | 66.64 ms | 72.11 ms |
| p95 call latency | 77.35 ms | 83.21 ms |
| Output cap witness | rejects at 128 bytes | accepts 3,893 bytes |
| Compared source lines | 366 | 42 |
| Additional third-party dependencies | 0 | 0 |

Simplified p95 regressed by 7.58% in this run. More decisively, a finite fake
tshark emitting 1,000 valid frame numbers reproduces the safety difference:
Full reports `output_limit`; Simplified accepts all output. The witness is
small and bounded and does not attempt to exhaust memory.

The final Docker suite passed 156 tests with 95.86% total branch-aware
coverage. Compiler coverage was 98%, field catalog/validator 91%, evaluator
99%, live boundary 100%, fixtures 100%, and runner 96%. Pyright strict,
Pylint 10/10, Pyink, isort, and the core import contract passed.

Production container inspection verified UID/GID 10001, read-only root,
network `none`, all capabilities dropped, no-new-privileges, one CPU, 512 MiB,
128 PIDs, init enabled, and a 64 MiB noexec tmpfs. No Docker socket was mounted.
The binary reports Lua absent and native plugins disabled at compile time.
Test containers use an executable tmpfs for process-test doubles; production
retains noexec.

## Decision and limits

Keep the protected runner. Deleting output and lifecycle safeguards is not
behaviorally safe even when the curated packet sets match. Keep one Python
distribution and standard-library fixture generation; no service abstraction
or new application dependency was introduced.

The nine-probe fixture suite verifies this slice only. It does not verify the
50-capture/150-filter stability gate, model compile-validity or silent-wrong
rates, the full mutation benchmark, or general sandbox escape resistance.
Receipt hashes include measured runtimes; repeated stability is assessed with
separate packet-set hashes. `replay-run` validates receipts and optional
environment identity without re-executing tshark. The Web remains a recorded
demo, and the earlier core/Web runtime ablations are still outstanding.

## Addendum: exit-status classification

Measured: 2026-09-19. Scope: the runner's failure codes only; the decision
above is unchanged.

Full is the classified runner: exit 4 becomes `filter_rejected`, or
`filter_unknown_field` when tshark's own first stderr line is its "is not a
valid protocol or protocol field" sentence; exit 3 or 14 becomes
`capture_unreadable`; every other non-zero status stays `tshark_failed`.
Simplified is the mapping at revision `1c64140`, where any non-zero status is
`tshark_failed`. The valid capture is the first pilot probe,
`tcp-syn-no-ack-17.pcap`; the truncated and garbage captures are derived from
it during the run and are not retained. Each row below is a row of the
measurements file, which names every capture in its `capture` column.

| Kind | Filter | Capture | Exit | Full | Simplified |
| --- | --- | --- | ---: | --- | --- |
| filter | `ip.ttll` | valid | 4 | filter_unknown_field | tshark_failed |
| filter | `tcp &&` | valid | 4 | filter_rejected | tshark_failed |
| filter | `ip.ttl <= "abc"` | valid | 4 | filter_rejected | tshark_failed |
| capture | `tcp` | truncated | 14 | capture_unreadable | tshark_failed |
| capture | `tcp` | garbage | 3 | capture_unreadable | tshark_failed |
| filter | `ip.ttll` | garbage | 4 | filter_unknown_field | tshark_failed |

Full separates filter failures from capture failures on all six witnesses;
Simplified separates none. The classification adds 66 lines to
`src/dfilterforge/runner.py` and removes 9, and it keeps stderr out of every
message: only the exit status and a 256-byte first-line match choose the code.
The truncated capture prints two frames before tshark fails, the
`stdout_frames` column of the same row, and Full discards them rather than
returning a short result.

Decision: keep Full. A scorer that cannot tell a rejected model filter from an
unreadable probe capture charges a harness failure to the model. The typed
receipt still records `keep_protected` from the output-cap witness above; this
addendum adds no new ablation number.

```text
docker compose --profile dev run --rm --volume "${PWD}/src:/workspace/src:ro" --volume "${PWD}/scripts:/workspace/scripts:ro" --volume "${PWD}/artifacts:/workspace/artifacts" test python scripts/runner_ablation.py --fixtures /workspace/artifacts/pilot --output /workspace/artifacts/runner-exit-status.json --code-revision 1c64140+working-tree
docker compose --profile pilot run --rm lab ablation run --manifest /workspace/artifacts/runner-exit-status.receipt.json
```

Raw measurements: `evidence/001-runner-measurements.json`.
Typed ablation receipt: `evidence/001-runner-receipt.json`.
Exit-status measurements: `evidence/001-exit-status-measurements.json`.
Exit-status receipt: `evidence/001-exit-status-measurements.receipt.json`.
