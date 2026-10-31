# Repair summary

Model: qwen3-1.7b-sft-s42. Split: dev. Base run: dev-qwen3-1.7b-sft-s42-2026-10-07. Feedback probe: semantic-29.
Triggered: 17 items in 10 cases (11 silent-wrong, 6 invalid). Cards: 11 frames, 6 error, 0 none.
Base manifest f46b047f1007, base outcomes 370e0f93aadb, plan 7222d52b3736, gold hash 6597c4d22cb9.
Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, drawn from 12 ready cases of the base pass.

## Arms

| Arm | Run | repair@1 | Silent-wrong part | Invalid part | Repaired | Shortcut | Answer unchanged | Card value reuse | Latency p50 ms | Charged USD | Provider USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resample | dev-qwen3-1.7b-sft-s42-res-2026-10-07 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/17 | 0 | 15 | - | 2422 | 0.000232 | - |
| bare | dev-qwen3-1.7b-sft-s42-bare-2026-10-07 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/17 | 0 | 5 | - | 1594 | 0.000246 | - |
| counterexample | dev-qwen3-1.7b-sft-s42-cx-2026-10-07 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/17 | 0 | 3 | 0 | 1547 | 0.000274 | - |

Arms not run: none.

repair@1 is the triggered items made strong exact over the triggered items, as summed case shares of each case's C4 items. A shortcut, a provider failure or any other outcome is not repaired. Answer unchanged and card value reuse are diagnostics, never outcomes.

## Comparisons

| Comparison | Difference | First better | Second better | Discordant | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| counterexample - bare | 0.000 [0.000, 0.000] | 0 | 0 | 0 | inconclusive (fewer than 10 discordant cases) |
| counterexample - resample | 0.000 [0.000, 0.000] | 0 | 0 | 0 | inconclusive (fewer than 10 discordant cases) |
| bare - resample | 0.000 [0.000, 0.000] | 0 | 0 | 0 | inconclusive (fewer than 10 discordant cases) |

## Transitions

| Arm | Base outcome | Arm outcome | Items |
| --- | --- | --- | ---: |
| resample | invalid | invalid | 6 |
| resample | silent_wrong | silent_wrong | 11 |
| bare | invalid | malformed | 1 |
| bare | invalid | abstained | 4 |
| bare | invalid | invalid | 1 |
| bare | silent_wrong | malformed | 2 |
| bare | silent_wrong | abstained | 3 |
| bare | silent_wrong | silent_wrong | 6 |
| counterexample | invalid | malformed | 1 |
| counterexample | invalid | abstained | 5 |
| counterexample | silent_wrong | malformed | 1 |
| counterexample | silent_wrong | abstained | 6 |
| counterexample | silent_wrong | silent_wrong | 4 |

## Items

| Item | Case | Base outcome | Base outcome now | Card | resample | bare | counterexample |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mei-0001 | tcp-expiring-ttl | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-0003 | udp-expiring-ttl | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | abstained |
| mei-0006 | ack-to-https | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | abstained |
| mei-0007 | dns-a-queries | invalid | invalid | error | invalid | malformed | malformed |
| mei-0008 | dns-a-queries | invalid | invalid | error | invalid | invalid | abstained |
| mei-0011 | udp-nondns-private-destination | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | abstained |
| mei-0012 | udp-nondns-private-destination | invalid | invalid | error | invalid | abstained | abstained |
| mei-0013 | ecn-syn-or-expiring | invalid | invalid | error | invalid | abstained | abstained |
| mei-0014 | ecn-syn-or-expiring | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-0015 | aaaa-or-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | abstained | malformed |
| mei-0016 | aaaa-or-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | abstained | silent_wrong |
| mei-0017 | reset-or-fin | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | abstained |
| mei-0018 | reset-or-fin | invalid | invalid | error | invalid | abstained | abstained |
| mei-0019 | udp-normal-ttl | invalid | invalid | error | invalid | abstained | abstained |
| mei-0020 | udp-normal-ttl | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-0023 | dns-error-responses | silent_wrong | silent_wrong | frames | silent_wrong | malformed | abstained |
| mei-0024 | dns-error-responses | silent_wrong | silent_wrong | frames | silent_wrong | malformed | silent_wrong |

Base outcome changed since the plan: none.
