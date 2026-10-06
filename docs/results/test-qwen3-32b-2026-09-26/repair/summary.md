# Repair summary

Model: qwen/qwen3-32b. Split: test. Base run: test-qwen3-32b-2026-09-26. Feedback probe: semantic-35.
Triggered: 28 items in 20 cases (25 silent-wrong, 3 invalid). Cards: 25 frames, 3 error, 0 none.
Base manifest 2e4879bd9e9b, base outcomes 6ba131f5396b, plan 67ba5bcbfa4d, gold hash a9632daadafe.
Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, drawn from 40 ready cases of the base pass.

## Arms

| Arm | Run | repair@1 | Silent-wrong part | Invalid part | Repaired | Shortcut | Answer unchanged | Card value reuse | Latency p50 ms | Charged USD | Provider USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resample | test-qwen3-32b-res-2026-09-26 | 0.036 [0.000, 0.115] | 0.040 [0.000, 0.130] | 0.000 [0.000, 0.000] | 1/28 | 0 | 16 | - | 9906 | 0.005015 | 0.004997 |
| bare | test-qwen3-32b-bare-2026-09-26 | 0.500 [0.292, 0.696] | 0.520 [0.280, 0.733] | 0.333 [0.000, 1.000] | 14/28 | 0 | 3 | - | 9797 | 0.005585 | 0.005571 |
| counterexample | test-qwen3-32b-cx-2026-09-26 | 0.571 [0.350, 0.759] | 0.600 [0.368, 0.792] | 0.333 [0.000, 1.000] | 16/28 | 0 | 3 | 11 | 10203 | 0.006182 | 0.006169 |

Arms not run: none.

repair@1 is the triggered items made strong exact over the triggered items, as summed case shares of each case's C4 items. A shortcut, a provider failure or any other outcome is not repaired. Answer unchanged and card value reuse are diagnostics, never outcomes.

## Comparisons

| Comparison | Difference | First better | Second better | Discordant | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| counterexample - bare | 0.071 [-0.069, 0.207] | 3 | 1 | 4 | inconclusive (fewer than 10 discordant cases) |
| counterexample - resample | 0.536 [0.333, 0.720] | 12 | 0 | 12 | conclusive |
| bare - resample | 0.464 [0.259, 0.645] | 10 | 0 | 10 | conclusive |

## Transitions

| Arm | Base outcome | Arm outcome | Items |
| --- | --- | --- | ---: |
| resample | invalid | invalid | 2 |
| resample | invalid | silent_wrong | 1 |
| resample | silent_wrong | malformed | 2 |
| resample | silent_wrong | silent_wrong | 22 |
| resample | silent_wrong | strong_exact | 1 |
| bare | invalid | invalid | 2 |
| bare | invalid | strong_exact | 1 |
| bare | silent_wrong | malformed | 1 |
| bare | silent_wrong | invalid | 2 |
| bare | silent_wrong | silent_wrong | 9 |
| bare | silent_wrong | strong_exact | 13 |
| counterexample | invalid | silent_wrong | 2 |
| counterexample | invalid | strong_exact | 1 |
| counterexample | silent_wrong | malformed | 2 |
| counterexample | silent_wrong | invalid | 1 |
| counterexample | silent_wrong | silent_wrong | 7 |
| counterexample | silent_wrong | strong_exact | 15 |

## Items

| Item | Case | Base outcome | Base outcome now | Card | resample | bare | counterexample |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mei-1001 | tcp-source-testnet | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | strong_exact |
| mei-1002 | tcp-source-testnet | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | strong_exact |
| mei-1003 | udp-source-testnet | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | strong_exact |
| mei-1008 | source-testnet-or-private | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-1017 | low-port-dns-a | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |
| mei-1018 | low-port-dns-a | silent_wrong | silent_wrong | frames | silent_wrong | invalid | silent_wrong |
| mei-1022 | successful-source-dns | invalid | invalid | error | silent_wrong | strong_exact | silent_wrong |
| mei-1023 | aaaa-or-udp-source-dns | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-1025 | https-without-syn | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | strong_exact |
| mei-1026 | https-without-syn | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | strong_exact |
| mei-1027 | https-syn-no-ack | silent_wrong | silent_wrong | frames | strong_exact | strong_exact | strong_exact |
| mei-1028 | https-syn-no-ack | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | strong_exact |
| mei-1029 | https-syn-or-reset | invalid | invalid | error | invalid | invalid | silent_wrong |
| mei-1030 | https-syn-or-reset | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | strong_exact |
| mei-1037 | fin-from-https-port | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | strong_exact |
| mei-1038 | fin-from-https-port | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | strong_exact |
| mei-1040 | ece-any-segment | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |
| mei-1042 | cwr-any-segment | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-1045 | control-segments | silent_wrong | silent_wrong | frames | silent_wrong | invalid | invalid |
| mei-1048 | https-no-syn-no-reset | invalid | invalid | error | invalid | invalid | strong_exact |
| mei-1051 | ack-no-payload | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-1055 | ttl-between | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | strong_exact |
| mei-1059 | dns-query-off-port-53 | silent_wrong | silent_wrong | frames | malformed | silent_wrong | silent_wrong |
| mei-1061 | dns-response-not-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | malformed |
| mei-1062 | dns-response-not-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | malformed | malformed |
| mei-1067 | dns-except-nxdomain | silent_wrong | silent_wrong | frames | malformed | silent_wrong | silent_wrong |
| mei-1068 | dns-except-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | strong_exact |
| mei-1080 | https-from-outside-testnet | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | strong_exact |

Base outcome changed since the plan: none.
