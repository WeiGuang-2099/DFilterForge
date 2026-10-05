# Repair summary

Model: deepseek/deepseek-v4-pro-0813. Split: dev. Base run: dev-deepseek-v4-pro-0813-2026-09-26. Feedback probe: semantic-29.
Triggered: 11 items in 7 cases (9 silent-wrong, 2 invalid). Cards: 9 frames, 2 error, 0 none.
Base manifest 298affadb2cd, base outcomes bd7d7a34f13c, plan c2e75d74b17a, gold hash 6597c4d22cb9.
Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, drawn from 12 ready cases of the base pass.

## Arms

| Arm | Run | repair@1 | Silent-wrong part | Invalid part | Repaired | Shortcut | Answer unchanged | Card value reuse | Latency p50 ms | Charged USD | Provider USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resample | dev-deepseek-v4-pro-0813-res-nb-2026-09-26 | 0.182 [0.000, 0.444] | 0.222 [0.000, 0.500] | 0.000 [0.000, 0.000] | 2/11 | 0 | 0 | - | 4828 | 0.024761 | 0.024756 |
| bare | dev-deepseek-v4-pro-0813-bare-nb-2026-09-26 | 0.091 [0.000, 0.333] | 0.111 [0.000, 0.400] | 0.000 [0.000, 0.000] | 1/11 | 0 | 2 | - | 4359 | 0.026496 | 0.026489 |
| counterexample | dev-deepseek-v4-pro-0813-cx-nb-2026-09-26 | 0.636 [0.333, 1.000] | 0.778 [0.500, 1.000] | 0.000 [0.000, 0.000] | 7/11 | 0 | 1 | 3 | 3860 | 0.027363 | 0.027358 |

Arms not run: none.

repair@1 is the triggered items made strong exact over the triggered items, as summed case shares of each case's C4 items. A shortcut, a provider failure or any other outcome is not repaired. Answer unchanged and card value reuse are diagnostics, never outcomes.

## Comparisons

| Comparison | Difference | First better | Second better | Discordant | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| counterexample - bare | 0.545 [0.250, 0.857] | 5 | 0 | 5 | inconclusive (fewer than 10 discordant cases) |
| counterexample - resample | 0.455 [0.125, 0.846] | 4 | 0 | 4 | inconclusive (fewer than 10 discordant cases) |
| bare - resample | -0.091 [-0.273, 0.000] | 0 | 1 | 1 | inconclusive (fewer than 10 discordant cases) |

## Transitions

| Arm | Base outcome | Arm outcome | Items |
| --- | --- | --- | ---: |
| resample | invalid | invalid | 1 |
| resample | invalid | silent_wrong | 1 |
| resample | silent_wrong | invalid | 1 |
| resample | silent_wrong | silent_wrong | 6 |
| resample | silent_wrong | strong_exact | 2 |
| bare | invalid | invalid | 1 |
| bare | invalid | silent_wrong | 1 |
| bare | silent_wrong | silent_wrong | 8 |
| bare | silent_wrong | strong_exact | 1 |
| counterexample | invalid | silent_wrong | 2 |
| counterexample | silent_wrong | invalid | 1 |
| counterexample | silent_wrong | silent_wrong | 1 |
| counterexample | silent_wrong | strong_exact | 7 |

## Items

| Item | Case | Base outcome | Base outcome now | Card | resample | bare | counterexample |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mei-0007 | dns-a-queries | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |
| mei-0008 | dns-a-queries | invalid | invalid | error | silent_wrong | silent_wrong | silent_wrong |
| mei-0009 | fin-or-dns-response | silent_wrong | silent_wrong | frames | strong_exact | silent_wrong | silent_wrong |
| mei-0010 | fin-or-dns-response | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |
| mei-0012 | udp-nondns-private-destination | silent_wrong | silent_wrong | frames | strong_exact | strong_exact | strong_exact |
| mei-0013 | ecn-syn-or-expiring | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |
| mei-0014 | ecn-syn-or-expiring | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |
| mei-0015 | aaaa-or-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |
| mei-0017 | reset-or-fin | silent_wrong | silent_wrong | frames | invalid | silent_wrong | invalid |
| mei-0018 | reset-or-fin | invalid | invalid | error | invalid | invalid | silent_wrong |
| mei-0024 | dns-error-responses | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |

Base outcome changed since the plan: none.
