# Repair summary

Model: qwen3-1.7b-sft-s2026. Split: test. Base run: test-qwen3-1.7b-sft-s2026-2026-10-07. Feedback probe: semantic-35.
Triggered: 36 items in 26 cases (25 silent-wrong, 11 invalid). Cards: 25 frames, 11 error, 0 none.
Base manifest 5cd820c6c568, base outcomes fe4b865ea3af, plan 87dbce5dd60d, gold hash a9632daadafe.
Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, drawn from 40 ready cases of the base pass.

## Arms

| Arm | Run | repair@1 | Silent-wrong part | Invalid part | Repaired | Shortcut | Answer unchanged | Card value reuse | Latency p50 ms | Charged USD | Provider USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resample | test-qwen3-1.7b-sft-s2026-res-2026-10-07 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/36 | 0 | 31 | - | 2750 | 0.000519 | - |
| bare | test-qwen3-1.7b-sft-s2026-bare-2026-10-07 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/36 | 0 | 2 | - | 1625 | 0.000546 | - |
| counterexample | test-qwen3-1.7b-sft-s2026-cx-2026-10-07 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/36 | 0 | 7 | 0 | 1797 | 0.000619 | - |

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
| resample | invalid | invalid | 11 |
| resample | silent_wrong | abstained | 1 |
| resample | silent_wrong | silent_wrong | 24 |
| bare | invalid | malformed | 6 |
| bare | invalid | abstained | 4 |
| bare | invalid | invalid | 1 |
| bare | silent_wrong | malformed | 6 |
| bare | silent_wrong | abstained | 18 |
| bare | silent_wrong | silent_wrong | 1 |
| counterexample | invalid | malformed | 2 |
| counterexample | invalid | abstained | 9 |
| counterexample | silent_wrong | malformed | 4 |
| counterexample | silent_wrong | abstained | 14 |
| counterexample | silent_wrong | silent_wrong | 7 |

## Items

| Item | Case | Base outcome | Base outcome now | Card | resample | bare | counterexample |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mei-1002 | tcp-source-testnet | silent_wrong | silent_wrong | frames | silent_wrong | malformed | abstained |
| mei-1004 | udp-source-testnet | silent_wrong | silent_wrong | frames | abstained | abstained | malformed |
| mei-1005 | private-either-endpoint | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1006 | private-either-endpoint | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1007 | source-testnet-or-private | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1008 | source-testnet-or-private | silent_wrong | silent_wrong | frames | silent_wrong | abstained | malformed |
| mei-1012 | high-udp-source-testnet | invalid | invalid | error | invalid | invalid | abstained |
| mei-1013 | high-udp-normal-ttl | silent_wrong | silent_wrong | frames | silent_wrong | malformed | silent_wrong |
| mei-1016 | high-udp-testnet-normal-ttl | invalid | invalid | error | invalid | malformed | abstained |
| mei-1019 | dns-destination-not-source | silent_wrong | silent_wrong | frames | silent_wrong | abstained | silent_wrong |
| mei-1020 | dns-destination-not-source | invalid | invalid | error | invalid | abstained | abstained |
| mei-1021 | successful-source-dns | silent_wrong | silent_wrong | frames | silent_wrong | malformed | silent_wrong |
| mei-1022 | successful-source-dns | silent_wrong | silent_wrong | frames | silent_wrong | abstained | silent_wrong |
| mei-1023 | aaaa-or-udp-source-dns | invalid | invalid | error | invalid | malformed | malformed |
| mei-1031 | tcp-destination-not-https | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1032 | tcp-destination-not-https | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1036 | tcp-without-port-443 | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1042 | cwr-any-segment | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1043 | syn-without-ece | invalid | invalid | error | invalid | abstained | abstained |
| mei-1044 | syn-without-ece | invalid | invalid | error | invalid | abstained | malformed |
| mei-1045 | control-segments | silent_wrong | silent_wrong | frames | silent_wrong | abstained | silent_wrong |
| mei-1046 | control-segments | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-1047 | https-no-syn-no-reset | invalid | invalid | error | invalid | abstained | abstained |
| mei-1052 | ack-no-payload | silent_wrong | silent_wrong | frames | silent_wrong | malformed | malformed |
| mei-1059 | dns-query-off-port-53 | silent_wrong | silent_wrong | frames | silent_wrong | malformed | malformed |
| mei-1061 | dns-response-not-nxdomain | invalid | invalid | error | invalid | malformed | abstained |
| mei-1062 | dns-response-not-nxdomain | invalid | invalid | error | invalid | malformed | abstained |
| mei-1066 | unicast-dns-udp-queries | silent_wrong | silent_wrong | frames | silent_wrong | malformed | abstained |
| mei-1067 | dns-except-nxdomain | invalid | invalid | error | invalid | malformed | abstained |
| mei-1068 | dns-except-nxdomain | invalid | invalid | error | invalid | malformed | abstained |
| mei-1070 | private-source-or-expiring | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1074 | no-testnet-endpoint | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1075 | udp-not-from-testnet | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1076 | udp-not-from-testnet | silent_wrong | silent_wrong | frames | silent_wrong | abstained | silent_wrong |
| mei-1077 | nondns-udp-from-testnet | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-1079 | https-from-outside-testnet | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |

Base outcome changed since the plan: none.
