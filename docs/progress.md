# Implementation Progress

Last updated: 2026-09-04

## Current slice

The first execution-grounded CLI slice is complete: bounded tshark runner,
three synthetic multi-probe cases, live evaluation, and measured receipts.

## Completed

- Durable agent rules and the implementation plan exist locally. Agent context,
  design drafts, and planning-only documents are excluded from Git.
- Python frozen contracts, deterministic compiler, field catalog, packet-set
  metrics, canonical receipts, replay validation, and the CLI are implemented.
- The final Docker Python suite passed 156 tests in 9.53 seconds with 95.86%
  total branch-aware coverage on 2026-09-04. Compiler coverage is 98%, field
  catalog/validator 91%, evaluator 99%, runner 96%, and live/fixtures 100%.
- Pyright strict, Pylint 10/10, Pyink, isort, and the core import contract passed
  against the final image. CI Python quality gates now use Docker.
- The recorded Evaluation Lab and supporting Workbench, Benchmark, Ablation,
  Receipt, and Methodology routes are implemented.
- The Web slice passed TypeScript checking, ESLint, a production Next.js build,
  and three Playwright journeys including axe serious/critical checks.
- A source-verified Wireshark 4.6.8 multi-stage Dockerfile, hardened Compose
  profiles, and CI quality gates are present. Compose configuration parses.
- `uv.lock` is generated and the local environment is pinned to Python 3.12.
- The empty local Git repository is initialized on `main`; the user-provided
  `origin` was inspected and had no remote refs before the initial push.
- Initial implementation commit `8f7eb4f` was pushed to `origin/main` and the
  local branch now tracks the remote branch.
- Docker Compose v5.3.0 is installed on the host.
- Docker Desktop 4.82.0 and the Linux daemon are running. Both production and
  test images built successfully from the verified Wireshark 4.6.8 archive.
- Fixed the Ubuntu nghttp2 package name, unsupported uv build flag, source
  build/install target mismatch, unlocked runtime dependency installation,
  and read-only test cache paths. Runtime dependencies now come from uv.lock
  with package hashes; the wheel build backend is pinned.
- The runner passes filters as argv with no shell, snapshots bounded captures,
  limits time/output/frame count, and kills the subprocess group. Safety tests
  cover hostile output, malformed frames, capture replacement, FIFO/symlink
  inputs, shell metacharacters, deadlines, and descendant cleanup.
- Three curated tasks generate nine PCAPs and 46 packets from seeds 17, 42,
  and 2026. Their compiler/reference results match independent labels and
  their near-wrong filters are distinguished on every probe.
- `fixtures generate` and `evaluate-live` are available. Live evaluation checks
  capture hashes and reference labels, records candidate differences, and
  writes measured environment sidecars plus receipt/packet-set hashes.
- Each production CLI case ran twice with stable packet-set and environment
  hashes. Three saved receipts passed replay validation with their environment
  hashes. Six receipts and sidecars are archived under
  `docs/ablations/evidence/001-receipts/`.
- Production inspection verified non-root, read-only root, no network, dropped
  capabilities, no-new-privileges, bounded CPU/memory/PIDs, init, and noexec
  tmpfs. The binary reports plugins disabled and Lua absent.
- Ablation 001 measured 81 paired Full/Simplified executions: all frame sets
  matched and all 27 mutation samples were killed. The simplified runner failed
  the output-cap witness, so the decision is `keep_protected`. Full p50/p95
  were 66.64/77.35 ms; Simplified were 72.11/83.21 ms.
- `docs/ablations/001-bounded-tshark-runner.md` records source/image/input hashes,
  reproducible commands, raw measurements, receipt hashes, and scope limits.

## In progress

- Freeze a catalog extracted from the actual pinned tshark binary and bind its
  profile/catalog identity to live compiler validation.
- Expand to 30-50 semantic specifications with multiple independent probes,
  reviewed labels, and near-wrong mutations.
- Record the still-outstanding executable ablations for the earlier core and
  recorded Web slices.

## Blocked or unverified

- All three Playwright cases pass, but the local Windows process does not exit
  cleanly after its development server is stopped. Linux CI teardown remains
  unverified; the Web production container was not exercised in this session.
- The nine-capture results do not establish the 50-capture/150-filter stability
  gate or broader pilot mutation/latency targets. Model compile validity,
  silent-wrong rates, baselines, SFT, DPO, and GRPO remain unmeasured.
- Container settings and tested process lifecycle controls do not constitute
  an exhaustive host/network escape audit.
- Environment sidecars identify the actual binary and runner policy/source,
  but explicitly exclude OCI digest and shared-library attestation. Outer
  Docker image IDs are recorded separately in the ablation report.
- The Web remains recorded-only. A live FastAPI boundary stays behind the
  measured Pilot Go/No-Go gate. Full predicate traces and execution replay
  remain future work; current replay validates stored receipts and metrics.

## Next verification

1. Extract and freeze the real tshark 4.6.8 catalog/profile and validate these
   three cases against it.
2. Grow the reviewed semantic suite to 30-50 tasks, with independent witnesses
   and known near-wrong mutations; keep split provenance and capture hashes.
3. Measure the 50-capture/150-filter determinism gate, oracle agreement, mutation
   kill rate, and latency before declaring those pilot targets verified.
4. Add predicate traces and executable replay, then model baselines and the
   Pilot Go/No-Go report in the implementation-plan order.
5. Verify the Web production container and Linux Playwright teardown before
   enabling any live Web job boundary.
