# Repair summary

Model: qwen/qwen3.5-9b. Split: test. Base run: test-qwen3.5-9b-2026-09-26. Feedback probe: semantic-35.
Triggered: 15 items in 11 cases (11 silent-wrong, 4 invalid). Cards: 11 frames, 4 error, 0 none.
Base manifest e5f7fcc247cc, base outcomes 428d5f51b052, plan c0f297cb96e0, gold hash a9632daadafe.
Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, drawn from 40 ready cases of the base pass.

## Arms

| Arm | Run | repair@1 | Silent-wrong part | Invalid part | Repaired | Shortcut | Answer unchanged | Card value reuse | Latency p50 ms | Charged USD | Provider USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resample | test-qwen3.5-9b-res-2026-09-26 | 0.067 [0.000, 0.214] | 0.091 [0.000, 0.250] | 0.000 [0.000, 0.000] | 1/15 | 0 | 5 | - | 7594 | 0.002971 | 0.002962 |
| bare | test-qwen3.5-9b-bare-2026-09-26 | 0.200 [0.000, 0.455] | 0.273 [0.000, 0.625] | 0.000 [0.000, 0.000] | 3/15 | 0 | 0 | - | 9766 | 0.003928 | 0.003920 |
| counterexample | test-qwen3.5-9b-cx-2026-09-26 | 0.400 [0.111, 0.714] | 0.364 [0.083, 0.667] | 0.500 [0.000, 1.000] | 6/15 | 0 | 0 | 2 | 8391 | 0.003906 | 0.003898 |

Arms not run: none.

repair@1 is the triggered items made strong exact over the triggered items, as summed case shares of each case's C4 items. A shortcut, a provider failure or any other outcome is not repaired. Answer unchanged and card value reuse are diagnostics, never outcomes.

## Comparisons

| Comparison | Difference | First better | Second better | Discordant | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| counterexample - bare | 0.200 [0.000, 0.450] | 2 | 0 | 2 | inconclusive (fewer than 10 discordant cases) |
| counterexample - resample | 0.333 [-0.050, 0.692] | 5 | 1 | 6 | inconclusive (fewer than 10 discordant cases) |
| bare - resample | 0.133 [-0.136, 0.444] | 3 | 1 | 4 | inconclusive (fewer than 10 discordant cases) |

## Transitions

| Arm | Base outcome | Arm outcome | Items |
| --- | --- | --- | ---: |
| resample | invalid | malformed | 1 |
| resample | invalid | invalid | 2 |
| resample | invalid | silent_wrong | 1 |
| resample | silent_wrong | abstained | 1 |
| resample | silent_wrong | silent_wrong | 9 |
| resample | silent_wrong | strong_exact | 1 |
| bare | invalid | invalid | 4 |
| bare | silent_wrong | malformed | 2 |
| bare | silent_wrong | abstained | 1 |
| bare | silent_wrong | silent_wrong | 5 |
| bare | silent_wrong | strong_exact | 3 |
| counterexample | invalid | malformed | 1 |
| counterexample | invalid | silent_wrong | 1 |
| counterexample | invalid | strong_exact | 2 |
| counterexample | silent_wrong | abstained | 3 |
| counterexample | silent_wrong | silent_wrong | 4 |
| counterexample | silent_wrong | strong_exact | 4 |

## Items

| Item | Case | Base outcome | Base outcome now | Card | resample | bare | counterexample |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mei-1025 | https-without-syn | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-1029 | https-syn-or-reset | invalid | invalid | error | silent_wrong | invalid | strong_exact |
| mei-1030 | https-syn-or-reset | invalid | invalid | error | invalid | invalid | strong_exact |
| mei-1037 | fin-from-https-port | silent_wrong | silent_wrong | frames | strong_exact | silent_wrong | abstained |
| mei-1038 | fin-from-https-port | silent_wrong | silent_wrong | frames | abstained | silent_wrong | silent_wrong |
| mei-1040 | ece-any-segment | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | strong_exact |
| mei-1045 | control-segments | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | abstained |
| mei-1046 | control-segments | invalid | invalid | error | invalid | invalid | silent_wrong |
| mei-1048 | https-no-syn-no-reset | silent_wrong | silent_wrong | frames | silent_wrong | malformed | silent_wrong |
| mei-1049 | ack-without-syn | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | strong_exact |
| mei-1051 | ack-no-payload | invalid | invalid | error | malformed | invalid | malformed |
| mei-1055 | ttl-between | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | strong_exact |
| mei-1061 | dns-response-not-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-1062 | dns-response-not-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | malformed | strong_exact |
| mei-1076 | udp-not-from-testnet | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |

Base outcome changed since the plan: none.
