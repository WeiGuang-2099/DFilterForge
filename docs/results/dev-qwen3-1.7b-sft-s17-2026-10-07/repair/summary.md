# Repair summary

Model: qwen3-1.7b-sft-s17. Split: dev. Base run: dev-qwen3-1.7b-sft-s17-2026-10-07. Feedback probe: semantic-29.
Triggered: 14 items in 9 cases (10 silent-wrong, 4 invalid). Cards: 10 frames, 4 error, 0 none.
Base manifest 197fb1303177, base outcomes dd243dbf9402, plan 521c6a3d0ce6, gold hash 6597c4d22cb9.
Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, drawn from 12 ready cases of the base pass.

## Arms

| Arm | Run | repair@1 | Silent-wrong part | Invalid part | Repaired | Shortcut | Answer unchanged | Card value reuse | Latency p50 ms | Charged USD | Provider USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resample | dev-qwen3-1.7b-sft-s17-res-2026-10-07 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/14 | 0 | 14 | - | 2422 | 0.000189 | - |
| bare | dev-qwen3-1.7b-sft-s17-bare-2026-10-07 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/14 | 0 | 0 | - | 1547 | 0.000199 | - |
| counterexample | dev-qwen3-1.7b-sft-s17-cx-2026-10-07 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/14 | 0 | 1 | 0 | 1547 | 0.000224 | - |

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
| resample | invalid | invalid | 4 |
| resample | silent_wrong | silent_wrong | 10 |
| bare | invalid | abstained | 4 |
| bare | silent_wrong | abstained | 10 |
| counterexample | invalid | abstained | 4 |
| counterexample | silent_wrong | malformed | 1 |
| counterexample | silent_wrong | abstained | 7 |
| counterexample | silent_wrong | silent_wrong | 2 |

## Items

| Item | Case | Base outcome | Base outcome now | Card | resample | bare | counterexample |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mei-0001 | tcp-expiring-ttl | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-0003 | udp-expiring-ttl | silent_wrong | silent_wrong | frames | silent_wrong | abstained | malformed |
| mei-0007 | dns-a-queries | invalid | invalid | error | invalid | abstained | abstained |
| mei-0008 | dns-a-queries | invalid | invalid | error | invalid | abstained | abstained |
| mei-0009 | fin-or-dns-response | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-0011 | udp-nondns-private-destination | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-0012 | udp-nondns-private-destination | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-0013 | ecn-syn-or-expiring | invalid | invalid | error | invalid | abstained | abstained |
| mei-0015 | aaaa-or-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-0016 | aaaa-or-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-0017 | reset-or-fin | silent_wrong | silent_wrong | frames | silent_wrong | abstained | silent_wrong |
| mei-0018 | reset-or-fin | invalid | invalid | error | invalid | abstained | abstained |
| mei-0019 | udp-normal-ttl | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-0020 | udp-normal-ttl | silent_wrong | silent_wrong | frames | silent_wrong | abstained | silent_wrong |

Base outcome changed since the plan: none.
