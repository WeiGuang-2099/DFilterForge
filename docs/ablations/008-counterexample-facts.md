# Ablation 008: Counterexample Facts

Status: keep_full

Measured: 2026-10-01

## Hypothesis

A repair card may show a model the feedback-probe frames its answer got wrong,
and it must say something about each frame that the model can act on without
seeing gold. The largest new abstraction in `dfilterforge.counterexample` is
the bounded header decoder with per-frame tshark confirmation. It is expected
to give every shown frame values that determine the feedback labels of every
ready case, for a fixed cost of one tshark run per frame, paid once per
capture. Membership facts alone are expected to determine no case. These are
the frame number and the two verdicts, which tshark's run of the answer and
the labels already give.

## Frozen inputs

- Full revision: `f29066e`, `src/` exported with `git archive`;
  `counterexample.py` sha256
  `951c02577538c55d7bed779f982b0a769421b97af7d9c04687bea98f14c4ff08`.
  - Receipt:
    [evidence/008-counterexample-facts-full.json](evidence/008-counterexample-facts-full.json),
    sha256 `1ca68316c8aaf9c1a54f53df8c908de1ccc79742a277e9f36fcb4fcb7d36bd52`.
- Simplified: `f29066e` plus
  [evidence/008-counterexample-facts-simplified.patch](evidence/008-counterexample-facts-simplified.patch),
  sha256 `7d97f5df51dd99db7133d1371ae99ef775ecf42b3b9fb2c704ad8794c552ecb8`;
  patched module sha256
  `b395284228bb9231c358e3de2450687ea2238f33936c903d668bd4be12022997`.
  - Receipt:
    [evidence/008-counterexample-facts-simplified.json](evidence/008-counterexample-facts-simplified.json),
    sha256 `2643d286d8aa0327b2f47fd2e674d70d6750c1f67fdac633642e80e43b986f13`.
- Measurement script:
  [evidence/008-counterexample-facts.py](evidence/008-counterexample-facts.py),
  sha256 `546b31041d62f6b8872378f33d6c2ba86ebcac89da5d4da231f7b625898ef38f`.
- Measurement identity, equal in both receipts:
  `dfc394eeb061774271346627263ce5d4d64a75c269159c91659ff8c6685c1a9d`.
  - It digests the environment, the gold file, both feedback captures and
    their label digests, the candidate list and the four dev base manifests.
  - It excludes the module, the results and the timings.
- Environment hash (both):
  `8bfb53d31c02b4c36786cd4914840f0808092a7e4fa037058248d4c4ba1bf414`.
  - tshark 4.6.8 in `dfilterforge-test:0.1.0`, image
    `sha256:841791ecaaa12b00357895a526c0b628e4bd9e099a03adcdda22d4e0b4ccd90d`,
    built 2026-09-26.
  - The module under test is not part of this hash, which covers the
    executable, the runner source and its limits.
- Dataset:
  - 52 ready cases, 12 dev and 40 test.
  - Feedback probes:
    - semantic-29 (dev): 62 frames, capture `1a0ef0e69d85`, labels
      `be0c91824bb5`;
    - semantic-35 (test): 63 frames, capture `3ca0673f7a0d`, labels
      `c0b30949787e`, the digest `docs/protocol.md` quotes.
  - Gold file `f59c6a095aec`.
  - 392 candidates, the leak-test set of `tests/test_counterexample.py`: the
    52 authored mutations and the 340 killed single-site mutants. Candidate
    list `1da68ee544b6`.
  - The 36 triggered C4 items of the four counted 2026-09-26 dev passes,
    through `repair.build_plan`.
- Seeds: none apply. Card building is deterministic, and each variant's cards
  were byte-identical across its three repetitions (`cards_sha256` per
  repetition in each receipt).
- Quality threshold:
  - Every leak check of `tests/test_counterexample.py` holds on all 392
    candidates, and no canonical IR gets a card.
  - Core metric: the ready cases whose labels the shown entries determine.
- Performance threshold: no more than 5 percent regression, Full against
  Simplified run back to back.

## Full

`dfilterforge.counterexample` reads each feedback capture once.

1. **Read.** The read is bounded by the runner's capture limit and checked
   against the digest the specification pins.
2. **Decode.** It decodes classic little-endian PCAP, Ethernet II, IPv4, TCP or
   UDP and a DNS header from that one buffer. Every offset is checked, and a
   compression pointer in the question is refused.
3. **Confirm.** For every frame, one filter built only from the typed decoded
   values must select exactly that frame, or the round stops with
   `facts_unproven`. The filter states each of the 13 shown fields equal to its
   value and each missing one absent, and it goes through `TsharkRunner.run`
   as argv.
4. **Card.** A card frame carries its number, `answer_matched`,
   `should_match` and those 13 fields.

Selection, the repeat-skip rule, the 1,024-byte cap and the error card are
the ones the repair-round design specifies; the protocol text is not yet
registered.

## Simplified

The patch is the real deletion of the facts. It removes:

- `HeaderFactsV1` and its 13 fields;
- the decoder: `decode_capture` and its TCP, UDP and DNS readers;
- `proof_filter`;
- the bounded, hash-checked capture read and `read_frame_facts`;
- `CardBuilder.facts`.

A card frame keeps only its number, `answer_matched` and `should_match`.
These are membership facts: tshark's run of the answer and the labels give
them.

Selection, the cap, the error card and every leak property are unchanged, and
`frames_card` no longer takes facts. The repeat-skip rule is unchanged as well:
it skips a frame equal to one already shown except for its number. With nothing
else on a frame, every further missed frame repeats the first, so a card shows
at most one missed and one wrongly selected frame.

The patched module passes pyink, pylint (exit 0) and pyright (0 errors) with
`repair.py` unchanged. `tests/test_counterexample.py` and `tests/test_repair.py`
fail at collection under it, because they import the deleted names or build
frames with header fields.

## Commands

From the repository root in Git Bash with `MSYS_NO_PATHCONV=1`. `$T` is a
scratch directory written in its `pwd -W` form, as Docker needs. On Windows, `git apply` outside a repository follows
`core.autocrlf`, so it is turned off to keep the module's bytes.

```text
R="$(pwd -W)"; mkdir -p "$T/full" "$T/simplified" "$T/out"
git archive f29066e src pyproject.toml | tar -x -C "$T/full"
git archive f29066e src pyproject.toml | tar -x -C "$T/simplified"
(cd "$T/simplified" && git -c core.autocrlf=false apply "$R/docs/ablations/evidence/008-counterexample-facts-simplified.patch")
for V in full simplified; do
  docker run --rm --network none --tmpfs /tmp:rw,exec,nosuid,nodev,size=256m \
    -v "$T/$V/src:/workspace/src:ro" -v "$T/$V/pyproject.toml:/workspace/pyproject.toml:ro" \
    -v "$R/docs/results:/results:ro" \
    -v "$R/docs/ablations/evidence/008-counterexample-facts.py:/workspace/measure.py:ro" \
    -v "$T/out:/out" dfilterforge-test:0.1.0 \
    python /workspace/measure.py --variant $V --output /out/008-counterexample-facts-$V.json \
    --source-revision f29066e --repetitions 3
done
```

How the recorded run differed from the commands above:

- The Simplified run passed `--source-revision f29066e+simplified`.
- The script was mounted from a scratch copy with the sha256 above.
- On 2026-10-01, Full ran from 12:15:06 to 12:19:55 UTC and Simplified from
  12:19:55 to 12:24:20 UTC, on one Windows 11 host under Docker Desktop.

What the script does:

1. **Facts.** For Full, it times each probe's facts read first.
2. **Cards.** It times the 392 cards, three times, with a fresh builder each
   time.
3. **Label determination.** It builds, for every frame of each case's feedback
   probe, the card the variant shows when only that frame disagrees. It groups
   the frames by that card's entry, without the number and verdicts and with
   every port from 41000 to 51254 read as one value.
   - A case is determined when no group mixes labelled and unlabelled frames.
   - The ports are masked because a rule that needs an ephemeral port is a
     shortcut (`protocol.md`, shortcut).
4. **Leak checks.** It runs the leak checks of `tests/test_counterexample.py`
   on every candidate's card.
5. **Plans.** It builds the four dev repair plans.
6. **Lines.** It counts the module's lines and public names.

## Results

| Measure | Full | Simplified | Delta |
| --- | ---: | ---: | ---: |
| Leak-check failures, 392 candidates | 0 | 0 | 0 |
| Canonical IRs given a card, of 52 | 0 | 0 | 0 |
| Frames whose shown values tshark confirmed (dev, test) | 62/62, 63/63 | none shown | |
| Header values shown and confirmed | 961 | 0 | -961 |
| Ready cases whose labels the shown entries determine | 52/52 | 0/52 | -52 |
| Cards with 1 / 2 / 3 frames | 107 / 66 / 219 | 345 / 47 / 0 | |
| Card bytes min / p50 / p95 / max | 183 / 562 / 694 / 717 | 67 / 68 / 123 / 124 | |
| Dev triggered items: frames / error / no card | 27 / 9 / 0 | 27 / 9 / 0 | 0 |
| Dev frames cards with 1 / 2 / 3 frames | 4 / 8 / 15 | 27 / 0 / 0 | |
| tshark runs to read the facts, both probes | 127 | 0 | -127 |
| Facts read, both probes (s, median of 3) | 8.85 | 0 | -8.85 |
| 392 cards (s, median of 3) | 66.00 | 67.61 | -2.4% |
| Card p50 / p95 (ms, median of 3) | 166.0 / 198.9 | 166.6 / 219.7 | |
| Facts and cards (s, median of 3) | 74.85 | 67.61 | +10.7% |
| Four dev plans, one run each (s) | 24.50 | 8.68 | +15.82 |
| Production lines: physical / nonblank / code | 805 / 705 / 554 | 318 / 263 / 195 | -487 / -442 / -359 |
| Public names | 20 | 12 | -8 |
| Modules | 1 | 1 | 0 |

**Context, not candidates.** Two other keys over Full's confirmed facts:

- **Addresses masked** (an option the repair-round design puts to the owner):
  37 of 52 cases are determined (10 dev, 27 test). The 15 others select by a
  private or TEST-NET range, as their case ids say.
- **The repair-round design's scratch key:** which of TCP, UDP and DNS a frame
  carries, plus its TCP flag names and its DNS response bit. This key
  determines 9 of 52 (2 dev, 7 test).
  - That design called this key "membership facts only" and measured 52, 37
    and 9 of 52 for the three keys. All three figures reproduce here.
  - The real deletion shows no per-frame field at all, so Simplified's 0/52 is
    the measured figure for this ablation.

**Real dev answers.** On the 36 triggered items the two variants agree on every
card kind: 27 frames cards for the silent-wrong answers and 9 error cards of
the same sizes (45 to 54 B), from code the patch leaves unchanged. Every real silent-wrong answer gets a card, so none
is feedback-blind. Every Simplified frames card shows a single frame. Full's
27 frames cards run from 227 to 717 B, median 604 B. The receipts hold each
plan's digest. Each Full plan takes about 4 s more than its Simplified twin,
which is the dev facts read; the plan step re-reads them once per base.

**Timing.** The facts read is a fixed cost per capture: 4.48 and 4.59 s for
the two probes in the first repetition, one `dns.flags` run plus one run per
frame. Per-card time does not change. The card phase varied from 61.1 to
77.2 s across the six repetitions, more than the 1.6 s between the two medians.

**Cap.** The largest card measured is 717 B, so the 1,024 B cap never bound.

## Decision

`keep_full`.

**What Simplified buys.** It saves 359 code lines, 8 public names and a fixed
8.85 s per round, about 4 s per plan.

**What it loses.** Its card shows nothing a model may act on:
- The frame number is a shortcut field.
- Under the repeat-skip rule every further missed frame repeats the
  first, so 345 of 392 cards and all 27 real dev frames cards show one frame.
- No ready case's labels follow from what it shows.

**What Full gives.** Every one of the 961 shown values is confirmed by tshark.
The shown entries determine all 52 cases' labels. Cards stay within 717 B.

**Performance.** Full fails the stated threshold: facts and cards together
take 10.7 percent longer. The whole difference is the one-time read of two
captures, and per-card time is unchanged within the measured spread. The
regression is accepted for the quality difference, as in ablation 004.

**Limits.**
- Determination is necessary for a card to teach the rule, not sufficient. It
  says a rule over the shown fields reproduces the labels, not that a model will
  find it. The counterexample-against-bare comparison of the repair round
  measures that.
- 15 cases need an address to be determined. Copying a host address that is not
  a stated network bound is still a shortcut, so the card cannot fake a repair
  that way.
- The timings are one host, three repetitions each, under Docker Desktop on
  Windows.
