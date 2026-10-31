# Repair summary

Model: qwen3-1.7b-sft-s17. Split: test. Base run: test-qwen3-1.7b-sft-s17-2026-10-07. Feedback probe: semantic-35.
Triggered: 45 items in 31 cases (32 silent-wrong, 13 invalid). Cards: 32 frames, 13 error, 0 none.
Base manifest 1d4812bfdd3c, base outcomes 0d78ae7b71cb, plan 3f997e7432a2, gold hash a9632daadafe.
Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, drawn from 40 ready cases of the base pass.

## Arms

| Arm | Run | repair@1 | Silent-wrong part | Invalid part | Repaired | Shortcut | Answer unchanged | Card value reuse | Latency p50 ms | Charged USD | Provider USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resample | test-qwen3-1.7b-sft-s17-res-2026-10-07 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/45 | 0 | 39 | - | 2891 | 0.000646 | - |
| bare | test-qwen3-1.7b-sft-s17-bare-2026-10-07 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/45 | 0 | 0 | - | 1578 | 0.000677 | - |
| counterexample | test-qwen3-1.7b-sft-s17-cx-2026-10-07 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/45 | 0 | 5 | 0 | 1609 | 0.000770 | - |

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
| resample | invalid | invalid | 12 |
| resample | invalid | silent_wrong | 1 |
| resample | silent_wrong | silent_wrong | 32 |
| bare | invalid | abstained | 13 |
| bare | silent_wrong | abstained | 32 |
| counterexample | invalid | abstained | 13 |
| counterexample | silent_wrong | abstained | 27 |
| counterexample | silent_wrong | silent_wrong | 5 |

## Items

| Item | Case | Base outcome | Base outcome now | Card | resample | bare | counterexample |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mei-1001 | tcp-source-testnet | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1002 | tcp-source-testnet | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1003 | udp-source-testnet | invalid | invalid | error | invalid | abstained | abstained |
| mei-1004 | udp-source-testnet | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1005 | private-either-endpoint | invalid | invalid | error | invalid | abstained | abstained |
| mei-1006 | private-either-endpoint | invalid | invalid | error | invalid | abstained | abstained |
| mei-1007 | source-testnet-or-private | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1008 | source-testnet-or-private | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1012 | high-udp-source-testnet | invalid | invalid | error | invalid | abstained | abstained |
| mei-1013 | high-udp-normal-ttl | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1016 | high-udp-testnet-normal-ttl | invalid | invalid | error | invalid | abstained | abstained |
| mei-1017 | low-port-dns-a | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1018 | low-port-dns-a | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1020 | dns-destination-not-source | invalid | invalid | error | invalid | abstained | abstained |
| mei-1021 | successful-source-dns | silent_wrong | silent_wrong | frames | silent_wrong | abstained | silent_wrong |
| mei-1022 | successful-source-dns | silent_wrong | silent_wrong | frames | silent_wrong | abstained | silent_wrong |
| mei-1023 | aaaa-or-udp-source-dns | invalid | invalid | error | invalid | abstained | abstained |
| mei-1024 | aaaa-or-udp-source-dns | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1025 | https-without-syn | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1028 | https-syn-no-ack | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1029 | https-syn-or-reset | invalid | invalid | error | silent_wrong | abstained | abstained |
| mei-1030 | https-syn-or-reset | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1031 | tcp-destination-not-https | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1032 | tcp-destination-not-https | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1036 | tcp-without-port-443 | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1037 | fin-from-https-port | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1041 | cwr-any-segment | silent_wrong | silent_wrong | frames | silent_wrong | abstained | silent_wrong |
| mei-1042 | cwr-any-segment | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1044 | syn-without-ece | invalid | invalid | error | invalid | abstained | abstained |
| mei-1045 | control-segments | silent_wrong | silent_wrong | frames | silent_wrong | abstained | silent_wrong |
| mei-1046 | control-segments | silent_wrong | silent_wrong | frames | silent_wrong | abstained | silent_wrong |
| mei-1047 | https-no-syn-no-reset | invalid | invalid | error | invalid | abstained | abstained |
| mei-1053 | udp-short-ttl | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1054 | udp-short-ttl | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1059 | dns-query-off-port-53 | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1061 | dns-response-not-nxdomain | invalid | invalid | error | invalid | abstained | abstained |
| mei-1062 | dns-response-not-nxdomain | invalid | invalid | error | invalid | abstained | abstained |
| mei-1063 | dns-queries-not-a | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1066 | unicast-dns-udp-queries | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1067 | dns-except-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1068 | dns-except-nxdomain | invalid | invalid | error | invalid | abstained | abstained |
| mei-1070 | private-source-or-expiring | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1074 | no-testnet-endpoint | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1075 | udp-not-from-testnet | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1077 | nondns-udp-from-testnet | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |

Base outcome changed since the plan: none.
