# Repair summary

Model: qwen/qwen3.5-122b-a10b. Split: test. Base run: test-qwen3.5-122b-a10b-2026-09-26. Feedback probe: semantic-35.
Triggered: 20 items in 16 cases (14 silent-wrong, 6 invalid). Cards: 14 frames, 6 error, 0 none.
Base manifest e4996dfd8898, base outcomes e04a52acfb45, plan a66dca952c6e, gold hash a9632daadafe.
Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, drawn from 40 ready cases of the base pass.

## Arms

| Arm | Run | repair@1 | Silent-wrong part | Invalid part | Repaired | Shortcut | Answer unchanged | Card value reuse | Latency p50 ms | Charged USD | Provider USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resample | test-qwen3.5-122b-a10b-res-2026-09-26 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/20 | 0 | 15 | - | 2547 | 0.031910 | 0.031903 |
| bare | test-qwen3.5-122b-a10b-bare-2026-09-26 | 0.100 [0.000, 0.250] | 0.143 [0.000, 0.400] | 0.000 [0.000, 0.000] | 2/20 | 0 | 8 | - | 2203 | 0.030387 | 0.030380 |
| counterexample | test-qwen3.5-122b-a10b-cx-2026-09-26 | 0.450 [0.267, 0.667] | 0.571 [0.333, 0.800] | 0.167 [0.000, 0.500] | 9/20 | 0 | 2 | 6 | 2282 | 0.036730 | 0.036722 |

Arms not run: none.

repair@1 is the triggered items made strong exact over the triggered items, as summed case shares of each case's C4 items. A shortcut, a provider failure or any other outcome is not repaired. Answer unchanged and card value reuse are diagnostics, never outcomes.

## Comparisons

| Comparison | Difference | First better | Second better | Discordant | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| counterexample - bare | 0.350 [0.056, 0.636] | 9 | 2 | 11 | conclusive |
| counterexample - resample | 0.450 [0.267, 0.667] | 9 | 0 | 9 | inconclusive (fewer than 10 discordant cases) |
| bare - resample | 0.100 [0.000, 0.250] | 2 | 0 | 2 | inconclusive (fewer than 10 discordant cases) |

## Transitions

| Arm | Base outcome | Arm outcome | Items |
| --- | --- | --- | ---: |
| resample | invalid | invalid | 6 |
| resample | silent_wrong | invalid | 1 |
| resample | silent_wrong | silent_wrong | 13 |
| bare | invalid | abstained | 2 |
| bare | invalid | invalid | 4 |
| bare | silent_wrong | abstained | 1 |
| bare | silent_wrong | invalid | 1 |
| bare | silent_wrong | silent_wrong | 10 |
| bare | silent_wrong | strong_exact | 2 |
| counterexample | invalid | abstained | 1 |
| counterexample | invalid | invalid | 2 |
| counterexample | invalid | silent_wrong | 2 |
| counterexample | invalid | strong_exact | 1 |
| counterexample | silent_wrong | malformed | 1 |
| counterexample | silent_wrong | invalid | 2 |
| counterexample | silent_wrong | silent_wrong | 3 |
| counterexample | silent_wrong | strong_exact | 8 |

## Items

| Item | Case | Base outcome | Base outcome now | Card | resample | bare | counterexample |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mei-1016 | high-udp-testnet-normal-ttl | silent_wrong | silent_wrong | frames | silent_wrong | abstained | strong_exact |
| mei-1018 | low-port-dns-a | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |
| mei-1021 | successful-source-dns | invalid | invalid | error | invalid | abstained | abstained |
| mei-1023 | aaaa-or-udp-source-dns | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |
| mei-1024 | aaaa-or-udp-source-dns | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | malformed |
| mei-1029 | https-syn-or-reset | invalid | invalid | error | invalid | invalid | silent_wrong |
| mei-1040 | ece-any-segment | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |
| mei-1042 | cwr-any-segment | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |
| mei-1045 | control-segments | silent_wrong | silent_wrong | frames | silent_wrong | invalid | invalid |
| mei-1048 | https-no-syn-no-reset | invalid | invalid | error | invalid | invalid | silent_wrong |
| mei-1051 | ack-no-payload | silent_wrong | silent_wrong | frames | invalid | strong_exact | invalid |
| mei-1052 | ack-no-payload | invalid | invalid | error | invalid | invalid | invalid |
| mei-1056 | ttl-between | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | silent_wrong |
| mei-1060 | dns-query-off-port-53 | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |
| mei-1061 | dns-response-not-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-1062 | dns-response-not-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |
| mei-1063 | dns-queries-not-a | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |
| mei-1064 | dns-queries-not-a | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-1066 | unicast-dns-udp-queries | invalid | invalid | error | invalid | invalid | strong_exact |
| mei-1068 | dns-except-nxdomain | invalid | invalid | error | invalid | abstained | invalid |

Base outcome changed since the plan: none.
