# DFilterForge

An LLM writes a Wireshark display filter, tshark disproves it with a packet
from a crafted probe capture, and one structured counterexample built from
that packet goes back to the model to repair it.

Live site: https://weiguang-2099.github.io/DFilterForge/

[![The home page: qwen/qwen3-32b's filter, its probe capture swept to frame 60, where the filter and the request disagree, then the counterexample card and a second answer exact on all three probes](docs/media/reel.gif)](https://weiguang-2099.github.io/DFilterForge/)

**After one structured counterexample, 35 of 75 failed test answers were
repaired, against 21 after a bare "your filter was incorrect" turn and 4
after a plain resample.** The 75 are every typed-IR (C4) answer to ready gold
on the frozen test split that four hosted models got silent-wrong or invalid;
an answer counts as repaired only if its new filter is strong exact on all
three scored probes. Pooled over the four models, repair@1 is 0.467
[0.347, 0.590] (95% case-level bootstrap). Per model, the registered primary
comparison, counterexample against bare, is conclusive only for the 120B,
qwen/qwen3.5-122b-a10b, where the counterexample did better in 9 cases and
bare in 2; for the other three models it is inconclusive
([locked test result](docs/results/locked-test-v1.md)).

Nothing is trained yet: every number above comes from hosted models.

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

## Usage

Development and the test suite, the three local execution cases, the frozen
field catalog, the semantic benchmark and a hosted model run are in
[docs/usage.md](docs/usage.md).

## Safety boundary

The public demo accepts only repository-curated captures. Do not expose tshark
or arbitrary capture upload directly to the public internet.

## License

MIT, see `LICENSE`. The Docker images build tshark from the Wireshark 4.6.8
source archive (GPL-2.0-or-later) and the frozen field catalog is derived from
that build; see `NOTICE`.
