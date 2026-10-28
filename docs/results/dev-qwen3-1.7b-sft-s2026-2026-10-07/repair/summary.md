# Repair summary

Model: qwen3-1.7b-sft-s2026. Split: dev. Base run: dev-qwen3-1.7b-sft-s2026-2026-10-07. Feedback probe: semantic-29.
Triggered: 15 items in 10 cases (10 silent-wrong, 5 invalid). Cards: 10 frames, 5 error, 0 none.
Base manifest 4c25059174be, base outcomes e62918524438, plan 5f0164f53f89, gold hash 6597c4d22cb9.
Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, drawn from 12 ready cases of the base pass.

## Arms

| Arm | Run | repair@1 | Silent-wrong part | Invalid part | Repaired | Shortcut | Answer unchanged | Card value reuse | Latency p50 ms | Charged USD | Provider USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resample | dev-qwen3-1.7b-sft-s2026-res-2026-10-07 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/15 | 0 | 12 | - | 2421 | 0.000204 | - |
| bare | dev-qwen3-1.7b-sft-s2026-bare-2026-10-07 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/15 | 0 | 5 | - | 1609 | 0.000215 | - |
| counterexample | dev-qwen3-1.7b-sft-s2026-cx-2026-10-07 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/15 | 0 | 3 | 0 | 1843 | 0.000240 | - |

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
| resample | invalid | invalid | 5 |
| resample | silent_wrong | silent_wrong | 10 |
| bare | invalid | malformed | 4 |
| bare | invalid | abstained | 1 |
| bare | silent_wrong | malformed | 3 |
| bare | silent_wrong | abstained | 2 |
| bare | silent_wrong | silent_wrong | 5 |
| counterexample | invalid | malformed | 3 |
| counterexample | invalid | abstained | 2 |
| counterexample | silent_wrong | abstained | 7 |
| counterexample | silent_wrong | silent_wrong | 3 |

## Items

| Item | Case | Base outcome | Base outcome now | Card | resample | bare | counterexample |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mei-0001 | tcp-expiring-ttl | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | abstained |
| mei-0003 | udp-expiring-ttl | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | abstained |
| mei-0007 | dns-a-queries | invalid | invalid | error | invalid | malformed | malformed |
| mei-0009 | fin-or-dns-response | silent_wrong | silent_wrong | frames | silent_wrong | malformed | abstained |
| mei-0011 | udp-nondns-private-destination | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-0012 | udp-nondns-private-destination | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-0013 | ecn-syn-or-expiring | invalid | invalid | error | invalid | malformed | malformed |
| mei-0015 | aaaa-or-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | malformed | silent_wrong |
| mei-0016 | aaaa-or-nxdomain | invalid | invalid | error | invalid | malformed | abstained |
| mei-0017 | reset-or-fin | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | abstained |
| mei-0018 | reset-or-fin | silent_wrong | silent_wrong | frames | silent_wrong | abstained | abstained |
| mei-0019 | udp-normal-ttl | silent_wrong | silent_wrong | frames | silent_wrong | malformed | abstained |
| mei-0020 | udp-normal-ttl | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | silent_wrong |
| mei-0023 | dns-error-responses | invalid | invalid | error | invalid | abstained | abstained |
| mei-0024 | dns-error-responses | invalid | invalid | error | invalid | malformed | malformed |

Base outcome changed since the plan: none.
