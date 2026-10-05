# Repair summary

Model: qwen/qwen3.5-122b-a10b. Split: dev. Base run: dev-qwen3.5-122b-a10b-2026-09-26. Feedback probe: semantic-29.
Triggered: 8 items in 7 cases (7 silent-wrong, 1 invalid). Cards: 7 frames, 1 error, 0 none.
Base manifest b1e5bdcc5c4c, base outcomes 678244151941, plan 6f746e8e067b, gold hash 6597c4d22cb9.
Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, drawn from 12 ready cases of the base pass.

## Arms

| Arm | Run | repair@1 | Silent-wrong part | Invalid part | Repaired | Shortcut | Answer unchanged | Card value reuse | Latency p50 ms | Charged USD | Provider USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resample | dev-qwen3.5-122b-a10b-res-2026-09-26 | 0.125 [0.000, 0.400] | 0.143 [0.000, 0.444] | 0.000 [0.000, 0.000] | 1/8 | 0 | 5 | - | 2687 | 0.011174 | 0.011172 |
| bare | dev-qwen3.5-122b-a10b-bare-2026-09-26 | 0.250 [0.000, 0.600] | 0.286 [0.000, 0.667] | 0.000 [0.000, 0.000] | 2/8 | 0 | 2 | - | 2937 | 0.012068 | 0.012064 |
| counterexample | dev-qwen3.5-122b-a10b-cx-2026-09-26 | 0.625 [0.250, 1.000] | 0.714 [0.333, 1.000] | 0.000 [0.000, 0.000] | 5/8 | 0 | 1 | 3 | 2766 | 0.012453 | 0.012449 |

Arms not run: none.

repair@1 is the triggered items made strong exact over the triggered items, as summed case shares of each case's C4 items. A shortcut, a provider failure or any other outcome is not repaired. Answer unchanged and card value reuse are diagnostics, never outcomes.

## Comparisons

| Comparison | Difference | First better | Second better | Discordant | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| counterexample - bare | 0.375 [-0.125, 1.000] | 4 | 1 | 5 | inconclusive (fewer than 10 discordant cases) |
| counterexample - resample | 0.500 [0.000, 1.000] | 5 | 1 | 6 | inconclusive (fewer than 10 discordant cases) |
| bare - resample | 0.125 [0.000, 0.429] | 1 | 0 | 1 | inconclusive (fewer than 10 discordant cases) |

## Transitions

| Arm | Base outcome | Arm outcome | Items |
| --- | --- | --- | ---: |
| resample | invalid | invalid | 1 |
| resample | silent_wrong | silent_wrong | 6 |
| resample | silent_wrong | strong_exact | 1 |
| bare | invalid | invalid | 1 |
| bare | silent_wrong | malformed | 1 |
| bare | silent_wrong | invalid | 2 |
| bare | silent_wrong | silent_wrong | 2 |
| bare | silent_wrong | strong_exact | 2 |
| counterexample | invalid | silent_wrong | 1 |
| counterexample | silent_wrong | invalid | 1 |
| counterexample | silent_wrong | silent_wrong | 1 |
| counterexample | silent_wrong | strong_exact | 5 |

## Items

| Item | Case | Base outcome | Base outcome now | Card | resample | bare | counterexample |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mei-0007 | dns-a-queries | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |
| mei-0010 | fin-or-dns-response | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | strong_exact |
| mei-0011 | udp-nondns-private-destination | silent_wrong | silent_wrong | frames | strong_exact | strong_exact | silent_wrong |
| mei-0013 | ecn-syn-or-expiring | silent_wrong | silent_wrong | frames | silent_wrong | malformed | strong_exact |
| mei-0016 | aaaa-or-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |
| mei-0017 | reset-or-fin | silent_wrong | silent_wrong | frames | silent_wrong | invalid | invalid |
| mei-0018 | reset-or-fin | invalid | invalid | error | invalid | invalid | silent_wrong |
| mei-0023 | dns-error-responses | silent_wrong | silent_wrong | frames | silent_wrong | invalid | strong_exact |

Base outcome changed since the plan: none.
