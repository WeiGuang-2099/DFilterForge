# Repair summary

Model: qwen/qwen3-32b. Split: dev. Base run: dev-qwen3-32b-2026-09-26. Feedback probe: semantic-29.
Triggered: 10 items in 6 cases (6 silent-wrong, 4 invalid). Cards: 6 frames, 4 error, 0 none.
Base manifest 6399a0001e5e, base outcomes 11ac7ec6d9ea, plan 53e110395c3e, gold hash 6597c4d22cb9.
Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, drawn from 12 ready cases of the base pass.

## Arms

| Arm | Run | repair@1 | Silent-wrong part | Invalid part | Repaired | Shortcut | Answer unchanged | Card value reuse | Latency p50 ms | Charged USD | Provider USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resample | dev-qwen3-32b-res-2026-09-26 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/10 | 0 | 7 | - | 7891 | 0.001543 | 0.001538 |
| bare | dev-qwen3-32b-bare-2026-09-26 | 0.200 [0.000, 0.417] | 0.167 [0.000, 0.500] | 0.250 [0.000, 0.500] | 2/10 | 0 | 2 | - | 8172 | 0.001779 | 0.001775 |
| counterexample | dev-qwen3-32b-cx-2026-09-26 | 0.400 [0.143, 0.750] | 0.500 [0.125, 1.000] | 0.250 [0.000, 0.500] | 4/10 | 0 | 1 | 2 | 7844 | 0.001937 | 0.001933 |

Arms not run: none.

repair@1 is the triggered items made strong exact over the triggered items, as summed case shares of each case's C4 items. A shortcut, a provider failure or any other outcome is not repaired. Answer unchanged and card value reuse are diagnostics, never outcomes.

## Comparisons

| Comparison | Difference | First better | Second better | Discordant | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| counterexample - bare | 0.200 [0.000, 0.600] | 2 | 0 | 2 | inconclusive (fewer than 10 discordant cases) |
| counterexample - resample | 0.400 [0.143, 0.750] | 4 | 0 | 4 | inconclusive (fewer than 10 discordant cases) |
| bare - resample | 0.200 [0.000, 0.417] | 2 | 0 | 2 | inconclusive (fewer than 10 discordant cases) |

## Transitions

| Arm | Base outcome | Arm outcome | Items |
| --- | --- | --- | ---: |
| resample | invalid | invalid | 3 |
| resample | invalid | silent_wrong | 1 |
| resample | silent_wrong | silent_wrong | 6 |
| bare | invalid | invalid | 2 |
| bare | invalid | silent_wrong | 1 |
| bare | invalid | strong_exact | 1 |
| bare | silent_wrong | invalid | 2 |
| bare | silent_wrong | silent_wrong | 3 |
| bare | silent_wrong | strong_exact | 1 |
| counterexample | invalid | malformed | 2 |
| counterexample | invalid | invalid | 1 |
| counterexample | invalid | strong_exact | 1 |
| counterexample | silent_wrong | silent_wrong | 3 |
| counterexample | silent_wrong | strong_exact | 3 |

## Items

| Item | Case | Base outcome | Base outcome now | Card | resample | bare | counterexample |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mei-0007 | dns-a-queries | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-0008 | dns-a-queries | silent_wrong | silent_wrong | frames | silent_wrong | invalid | silent_wrong |
| mei-0013 | ecn-syn-or-expiring | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | strong_exact |
| mei-0014 | ecn-syn-or-expiring | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-0015 | aaaa-or-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | invalid | strong_exact |
| mei-0017 | reset-or-fin | invalid | invalid | error | invalid | invalid | malformed |
| mei-0018 | reset-or-fin | invalid | invalid | error | invalid | invalid | malformed |
| mei-0020 | udp-normal-ttl | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |
| mei-0023 | dns-error-responses | invalid | invalid | error | silent_wrong | silent_wrong | invalid |
| mei-0024 | dns-error-responses | invalid | invalid | error | invalid | strong_exact | strong_exact |

Base outcome changed since the plan: none.
