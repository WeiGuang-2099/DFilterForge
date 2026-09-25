# Ablation 007: Feedback Probe

Status: keep_full

Measured: 2026-09-25

## Hypothesis

repair@1 needs packets to show a model that no score depends on
([protocol](../protocol.md)). One unscored capture per split, built like the
scored probes on its own seed, should separate every mutant the scored probes
kill, every authored mutation and every committed silent-wrong answer, give no
committed strong-exact answer a false counterexample, and move no scored gold.
The witness tail is expected to carry most of that, as it did for the scored
probes in [ablation 005](005-probe-witnesses.md).

The unit is one capture per split, not one per case as first planned: every
capture already holds all 20 recipes and all 33 witnesses, so a capture per case
would add bytes and hashes but no packet kind. A planned ARP witness was
dropped: every request tells the model to read it over complete Ethernet/IPv4
packets, so an ARP frame would mark answers wrong that the stated assumption
allows, it would change all six scored captures, and no gate mutant needs it.

## Frozen inputs

- Full revision: `11e01d7`; receipt
  [evidence/007-feedback-probe-full.json](evidence/007-feedback-probe-full.json),
  sha256 `b322b84d2421d4db00b610059d053d6ad0def91c4da5798db997ab45198038f2`,
  measurement identity `d4ca31aea6f113085a65bace641da84fc98c3214335898d354089c6a6b1517d4`.
- Simplified: `11e01d7` plus
  [evidence/007-feedback-probe-simplified.patch](evidence/007-feedback-probe-simplified.patch),
  sha256 `404c98e0a9eca14b42a0405d8707357f92a2c9e02fca4361b4b058004af17bd9`;
  receipt [evidence/007-feedback-probe-simplified.json](evidence/007-feedback-probe-simplified.json),
  sha256 `f8a965182e529215a4f7c9169960548f5224acd1af39f7fcbc3242cec697ede1`,
  measurement identity `7aff53745bdc4cca9911a9ef4492cdda1f3558447f06f7468e8117568bb40f16`.
- Seed control: `11e01d7` plus
  [evidence/007-feedback-probe-seed126.patch](evidence/007-feedback-probe-seed126.patch),
  sha256 `d7600e7e603a67e1d92907c2b2be4f16179dc51b7521c0efa1f420e2022baea3`;
  receipt [evidence/007-feedback-probe-seed126.json](evidence/007-feedback-probe-seed126.json),
  sha256 `08bfb6802aeb7507e76fda68cd88bbedac0a602055319eaa814851246189ed63`,
  measurement identity `949edc4d38d5897e69a3d88fff5034f432bf0a30ab8ebb08078521f8f700badf`.
- Environment hash (all three): `8bfb53d31c02b4c36786cd4914840f0808092a7e4fa037058248d4c4ba1bf414`,
  tshark 4.6.8 in the Docker test image built at `11e01d7`.
- Dataset: 52 ready cases (12 dev, 40 test), whole gold `ea17d038afe0`, scored
  capture manifest `035d86b42aee` (both unchanged in every variant), 344
  single-site mutants, and the 84 executed answers of the two committed dev runs
  (24 silent-wrong, 60 strong exact).
- Quality threshold: 0 on every strict key of gate 1.2, and no committed
  strong-exact answer separated on the feedback probe.
- Performance threshold: no more than 5 percent regression in tshark p50,
  Full against Simplified run back to back.

## Full

`dfilterforge.model_feedback` copies benchmark captures semantic-29 (dev, seed
128, client 192.0.2.129) and semantic-35 (test, seed 134, client 192.0.2.135)
into `feedback/` with the witness tail, through the same helper that copies the
scored probes, and gives each ready case its gold specification with that
capture as the only probe. Labels come from the same recipe and witness
memberships. No scored file, gold hash or model input changes, and import
contracts keep scoring and prompt building from the module. Gate
`probe-adequacy/1.2` checks the three gold filters on all eight probes and runs
every mutant on its split's feedback probe, which decides no survivor; it
fails on an authored mutation or a killed mutant equal to the labels there, and
on a waived survivor the feedback probe tells apart.

## Simplified

The patch deletes the tail from the feedback copies only: they are the
benchmark captures as generated, labelled from their recipes. The scored
probes, the gate and every other file are unchanged. The seed control is a
context run, reported under Results, not a candidate: it moves the test
feedback probe to semantic-27, whose client 192.0.2.127 lies inside
192.0.2.0/25.

## Commands

```text
docker compose --profile dev build test
docker compose --profile dev run --rm --volume "${PWD}/artifacts:/workspace/artifacts" test python scripts/probe_adequacy.py --output /workspace/artifacts/ablation-007/007-feedback-probe-full.json --source-revision 11e01d7 --report
docker compose --profile dev run --rm --volume "${PWD}/docs/results:/results:ro" --volume "${PWD}/docs/ablations/evidence/007-answer-replay.py:/tmp/replay.py:ro" test python /tmp/replay.py full
```

For Simplified and the seed control, the patched module was bind-mounted
read-only over `/workspace/src/dfilterforge/model_feedback.py` (the test image
installs the package editable) and the gate ran with `--source-revision
11e01d7+simplified` or `+seed126`. The answer replay
([script](evidence/007-answer-replay.py),
[output](evidence/007-answer-replay.json)) runs each committed answer's filter
on its case's feedback probe and compares the frames with the labels. It ran
for Full and, with the same mount, as `python /tmp/replay.py simplified`; the
output keeps the two printed objects under `full` and `simplified`. The seed
control needs no replay: it moves only the test probe, and every replayed
answer is on a dev case.

## Results

| Measure | Full | Simplified | Delta |
| --- | ---: | ---: | ---: |
| Label checks per filter | 416 | 416 | 0 |
| Label, canonical and mutation-label mismatches | 0 | 0 | 0 |
| Scored survivors (unwaived) | 4 (0) | 4 (0) | 0 |
| Killed mutants the feedback probe cannot tell apart (dev / test) | 0 | 112 (29 / 83) | -112 |
| Authored mutations equal to the labels there | 0 | 10 | -10 |
| Waived survivors it tells apart | 0 | 0 | 0 |
| Cases with an empty feedback label set | 0 | 4 | -4 |
| Committed silent-wrong answers separated | 24 / 24 | 18 / 24 | +6 |
| Committed strong-exact answers separated | 0 / 60 | 0 / 60 | 0 |
| Strict gate | pass | fail | |
| tshark p50 / p95 (ms) | 65.9 / 86.3 | 65.4 / 70.7 | +0.7% p50 |
| Timed runs / wall (s) | 2,576 / 178.6 | 2,576 / 170.5 | 0 / +4.7% |
| Production lines | 116 module, +85 net gate | 12 more in the module | -12 |

Without the tail, the blind mutants span eight of the ten operator families
(boundary 26, subnet 23, field-swap 18, value-domain 15, flag-as-number 13,
drop-conjunct 6, protocol-as-port 6, flag-as-byte 5; none from drop-disjunct or
drop-not). The six answers it misses are the ones the
witnesses were added for: in ack-to-https, `tcp.port == 443` for the
destination port (C1 mei-0005, first run) and `tcp.ack == 1` for the ACK flag
(C1 mei-0006, both runs); in ecn-syn-or-expiring, ECE without SYN (C4
mei-0013, both runs); and in udp-nondns-private-destination, `udp.port != 53`
for DNS (C3 mei-0011, second run). The seed control matches Full except for 11
blind mutants, all the /25 narrowing of a test TEST-NET-1 case. Against the
gate 1.1 receipt of the [case expansion](../decisions/case-expansion.md),
timed in another session, p50 was 3.1 percent higher and the gate ran about
52 s longer locally (1,932 to 2,576 timed runs); sessions differ by more than
that ([ablation 005](005-probe-witnesses.md)), so this is context, not the
threshold. The tail costs no code: the feedback copy reuses the
scored probes' copy helper, while the Simplified copy needs 12 lines of its
own.

## Decision

`keep_full`. With the tail, every killed mutant, every authored mutation and
every committed silent-wrong answer has a packet on the feedback probe, no
committed strong-exact answer gets a false one, and no scored hash moves;
without it, 112 mutants, 10 mutations and 6 real answers would get no
counterexample. Limits: the mutants come from a fixed operator set and the
silent-wrong answers from one model on 5 dev cases, so a real answer may be
feedback-blind; it stays in the repair@1 denominator, as pre-registered. The
feedback probe holds the same packet kinds as the scored probes with other
bytes, so repair@1 measures a fix after seeing a separating packet of a known
kind, not generalization to a new one. Server and fixed addresses repeat on
every probe; what a counterexample may quote is decided with its format.
