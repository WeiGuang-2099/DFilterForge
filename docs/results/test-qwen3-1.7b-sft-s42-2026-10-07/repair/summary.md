# Repair summary

Model: qwen3-1.7b-sft-s42. Split: test. Base run: test-qwen3-1.7b-sft-s42-2026-10-07. Feedback probe: semantic-35.
Triggered: 44 items in 30 cases (32 silent-wrong, 12 invalid). Cards: 32 frames, 12 error, 0 none.
Base manifest 15b8a2152684, base outcomes ea610b478e69, plan 45e46a6e29ff, gold hash a9632daadafe.
Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, drawn from 40 ready cases of the base pass.

## Arms

| Arm | Run | repair@1 | Silent-wrong part | Invalid part | Repaired | Shortcut | Answer unchanged | Card value reuse | Latency p50 ms | Charged USD | Provider USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resample | test-qwen3-1.7b-sft-s42-res-2026-10-07 | 0.023 [0.000, 0.079] | 0.031 [0.000, 0.103] | 0.000 [0.000, 0.000] | 1/44 | 0 | 39 | - | 3000 | 0.000659 | - |
| bare | test-qwen3-1.7b-sft-s42-bare-2026-10-07 | 0.045 [0.000, 0.114] | 0.062 [0.000, 0.154] | 0.000 [0.000, 0.000] | 2/44 | 0 | 4 | - | 1640 | 0.000690 | - |
| counterexample | test-qwen3-1.7b-sft-s42-cx-2026-10-07 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/44 | 0 | 6 | 0 | 1641 | 0.000774 | - |

Arms not run: none.

repair@1 is the triggered items made strong exact over the triggered items, as summed case shares of each case's C4 items. A shortcut, a provider failure or any other outcome is not repaired. Answer unchanged and card value reuse are diagnostics, never outcomes.

## Comparisons

| Comparison | Difference | First better | Second better | Discordant | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| counterexample - bare | -0.045 [-0.114, 0.000] | 0 | 2 | 2 | inconclusive (fewer than 10 discordant cases) |
| counterexample - resample | -0.023 [-0.079, 0.000] | 0 | 1 | 1 | inconclusive (fewer than 10 discordant cases) |
| bare - resample | 0.023 [-0.053, 0.100] | 2 | 1 | 3 | inconclusive (fewer than 10 discordant cases) |

## Transitions

| Arm | Base outcome | Arm outcome | Items |
| --- | --- | --- | ---: |
| resample | invalid | invalid | 11 |
| resample | invalid | silent_wrong | 1 |
| resample | silent_wrong | invalid | 1 |
| resample | silent_wrong | silent_wrong | 30 |
| resample | silent_wrong | strong_exact | 1 |
| bare | invalid | malformed | 6 |
| bare | invalid | abstained | 6 |
| bare | silent_wrong | malformed | 3 |
| bare | silent_wrong | abstained | 21 |
| bare | silent_wrong | silent_wrong | 6 |
| bare | silent_wrong | strong_exact | 2 |
| counterexample | invalid | malformed | 4 |
| counterexample | invalid | abstained | 8 |
| counterexample | silent_wrong | malformed | 2 |
| counterexample | silent_wrong | abstained | 24 |
| counterexample | silent_wrong | silent_wrong | 6 |

## Items

| Item | Case | Base outcome | Base outcome now | Card | resample | bare | counterexample |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mei-1002 | tcp-source-testnet | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1003 | udp-source-testnet | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1005 | private-either-endpoint | invalid | invalid | error | invalid | abstained | abstained |
| mei-1006 | private-either-endpoint | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | abstained |
| mei-1007 | source-testnet-or-private | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1008 | source-testnet-or-private | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1013 | high-udp-normal-ttl | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-1016 | high-udp-testnet-normal-ttl | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1017 | low-port-dns-a | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1018 | low-port-dns-a | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1020 | dns-destination-not-source | invalid | invalid | error | invalid | malformed | malformed |
| mei-1021 | successful-source-dns | invalid | invalid | error | invalid | abstained | abstained |
| mei-1022 | successful-source-dns | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-1023 | aaaa-or-udp-source-dns | invalid | invalid | error | invalid | malformed | malformed |
| mei-1024 | aaaa-or-udp-source-dns | silent_wrong | silent_wrong | frames | invalid | malformed | abstained |
| mei-1029 | https-syn-or-reset | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1031 | tcp-destination-not-https | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | abstained |
| mei-1032 | tcp-destination-not-https | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1035 | tcp-without-port-443 | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1036 | tcp-without-port-443 | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1040 | ece-any-segment | invalid | invalid | error | invalid | abstained | abstained |
| mei-1043 | syn-without-ece | silent_wrong | silent_wrong | frames | silent_wrong | abstained | malformed |
| mei-1044 | syn-without-ece | invalid | invalid | error | invalid | abstained | abstained |
| mei-1046 | control-segments | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-1047 | https-no-syn-no-reset | invalid | invalid | error | invalid | malformed | malformed |
| mei-1049 | ack-without-syn | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1050 | ack-without-syn | invalid | invalid | error | invalid | malformed | malformed |
| mei-1052 | ack-no-payload | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1053 | udp-short-ttl | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-1054 | udp-short-ttl | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | abstained |
| mei-1055 | ttl-between | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | abstained |
| mei-1059 | dns-query-off-port-53 | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1060 | dns-query-off-port-53 | silent_wrong | silent_wrong | frames | strong_exact | abstained | abstained |
| mei-1061 | dns-response-not-nxdomain | invalid | invalid | error | silent_wrong | malformed | abstained |
| mei-1062 | dns-response-not-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | malformed | silent_wrong |
| mei-1066 | unicast-dns-udp-queries | invalid | invalid | error | invalid | abstained | abstained |
| mei-1067 | dns-except-nxdomain | invalid | invalid | error | invalid | malformed | abstained |
| mei-1068 | dns-except-nxdomain | invalid | invalid | error | invalid | abstained | abstained |
| mei-1070 | private-source-or-expiring | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1074 | no-testnet-endpoint | silent_wrong | silent_wrong | frames | silent_wrong | malformed | abstained |
| mei-1075 | udp-not-from-testnet | silent_wrong | silent_wrong | frames | silent_wrong | abstained | silent_wrong |
| mei-1077 | nondns-udp-from-testnet | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1078 | nondns-udp-from-testnet | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1080 | https-from-outside-testnet | silent_wrong | silent_wrong | frames | silent_wrong | abstained | malformed |

Base outcome changed since the plan: none.
