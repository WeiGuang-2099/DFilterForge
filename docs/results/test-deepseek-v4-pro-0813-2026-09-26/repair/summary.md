# Repair summary

Model: deepseek/deepseek-v4-pro-0813. Split: test. Base run: test-deepseek-v4-pro-0813-2026-09-26. Feedback probe: semantic-35.
Triggered: 12 items in 9 cases (4 silent-wrong, 8 invalid). Cards: 4 frames, 8 error, 0 none.
Base manifest a771cec35f22, base outcomes 0b2403d95a20, plan 9281abbc3631, gold hash a9632daadafe.
Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, drawn from 40 ready cases of the base pass.

## Arms

| Arm | Run | repair@1 | Silent-wrong part | Invalid part | Repaired | Shortcut | Answer unchanged | Card value reuse | Latency p50 ms | Charged USD | Provider USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resample | test-deepseek-v4-pro-0813-res-2026-09-26 | 0.167 [0.000, 0.412] | 0.250 [0.000, 1.000] | 0.125 [0.000, 0.375] | 2/12 | 0 | 0 | - | 4610 | 0.027693 | 0.027687 |
| bare | test-deepseek-v4-pro-0813-bare-2026-09-26 | 0.167 [0.000, 0.500] | 0.500 [0.000, 1.000] | 0.000 [0.000, 0.000] | 2/12 | 0 | 1 | - | 4422 | 0.029299 | 0.029292 |
| counterexample | test-deepseek-v4-pro-0813-cx-2026-09-26 | 0.333 [0.083, 0.667] | 0.750 [0.000, 1.000] | 0.125 [0.000, 0.375] | 4/12 | 0 | 0 | 2 | 4391 | 0.030227 | 0.030220 |

Arms not run: none.

repair@1 is the triggered items made strong exact over the triggered items, as summed case shares of each case's C4 items. A shortcut, a provider failure or any other outcome is not repaired. Answer unchanged and card value reuse are diagnostics, never outcomes.

## Comparisons

| Comparison | Difference | First better | Second better | Discordant | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| counterexample - bare | 0.167 [-0.200, 0.500] | 3 | 1 | 4 | inconclusive (fewer than 10 discordant cases) |
| counterexample - resample | 0.167 [-0.286, 0.600] | 4 | 2 | 6 | inconclusive (fewer than 10 discordant cases) |
| bare - resample | 0.000 [-0.222, 0.308] | 1 | 1 | 2 | inconclusive (fewer than 10 discordant cases) |

## Transitions

| Arm | Base outcome | Arm outcome | Items |
| --- | --- | --- | ---: |
| resample | invalid | invalid | 6 |
| resample | invalid | silent_wrong | 1 |
| resample | invalid | strong_exact | 1 |
| resample | silent_wrong | malformed | 1 |
| resample | silent_wrong | silent_wrong | 2 |
| resample | silent_wrong | strong_exact | 1 |
| bare | invalid | invalid | 8 |
| bare | silent_wrong | silent_wrong | 2 |
| bare | silent_wrong | strong_exact | 2 |
| counterexample | invalid | invalid | 2 |
| counterexample | invalid | silent_wrong | 5 |
| counterexample | invalid | strong_exact | 1 |
| counterexample | silent_wrong | silent_wrong | 1 |
| counterexample | silent_wrong | strong_exact | 3 |

## Items

| Item | Case | Base outcome | Base outcome now | Card | resample | bare | counterexample |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mei-1024 | aaaa-or-udp-source-dns | silent_wrong | silent_wrong | frames | malformed | silent_wrong | strong_exact |
| mei-1029 | https-syn-or-reset | invalid | invalid | error | invalid | invalid | silent_wrong |
| mei-1030 | https-syn-or-reset | invalid | invalid | error | invalid | invalid | silent_wrong |
| mei-1032 | tcp-destination-not-https | silent_wrong | silent_wrong | frames | strong_exact | strong_exact | silent_wrong |
| mei-1042 | cwr-any-segment | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | strong_exact |
| mei-1045 | control-segments | invalid | invalid | error | invalid | invalid | silent_wrong |
| mei-1046 | control-segments | invalid | invalid | error | invalid | invalid | strong_exact |
| mei-1048 | https-no-syn-no-reset | invalid | invalid | error | invalid | invalid | silent_wrong |
| mei-1051 | ack-no-payload | invalid | invalid | error | strong_exact | invalid | invalid |
| mei-1052 | ack-no-payload | invalid | invalid | error | invalid | invalid | invalid |
| mei-1060 | dns-query-off-port-53 | invalid | invalid | error | silent_wrong | invalid | silent_wrong |
| mei-1061 | dns-response-not-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |

Base outcome changed since the plan: none.
