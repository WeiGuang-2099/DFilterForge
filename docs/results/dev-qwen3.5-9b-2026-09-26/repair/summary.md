# Repair summary

Model: qwen/qwen3.5-9b. Split: dev. Base run: dev-qwen3.5-9b-2026-09-26. Feedback probe: semantic-29.
Triggered: 7 items in 6 cases (5 silent-wrong, 2 invalid). Cards: 5 frames, 2 error, 0 none.
Base manifest 81586aa870cd, base outcomes 1559dbba636e, plan 387a330981b6, gold hash 6597c4d22cb9.
Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, drawn from 12 ready cases of the base pass.

## Arms

| Arm | Run | repair@1 | Silent-wrong part | Invalid part | Repaired | Shortcut | Answer unchanged | Card value reuse | Latency p50 ms | Charged USD | Provider USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resample | dev-qwen3.5-9b-res-2026-09-26 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0/7 | 0 | 2 | - | 26812 | 0.001224 | 0.001222 |
| bare | dev-qwen3.5-9b-bare-2026-09-26 | 0.143 [0.000, 0.500] | 0.200 [0.000, 0.800] | 0.000 [0.000, 0.000] | 1/7 | 0 | 2 | - | 21156 | 0.001761 | 0.001759 |
| counterexample | dev-qwen3.5-9b-cx-2026-09-26 | 0.429 [0.000, 0.818] | 0.600 [0.000, 1.000] | 0.000 [0.000, 0.000] | 3/7 | 0 | 0 | 3 | 13578 | 0.001883 | 0.001879 |

Arms not run: none.

repair@1 is the triggered items made strong exact over the triggered items, as summed case shares of each case's C4 items. A shortcut, a provider failure or any other outcome is not repaired. Answer unchanged and card value reuse are diagnostics, never outcomes.

## Comparisons

| Comparison | Difference | First better | Second better | Discordant | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| counterexample - bare | 0.286 [-0.400, 0.800] | 2 | 1 | 3 | inconclusive (fewer than 10 discordant cases) |
| counterexample - resample | 0.429 [0.000, 0.818] | 2 | 0 | 2 | inconclusive (fewer than 10 discordant cases) |
| bare - resample | 0.143 [0.000, 0.500] | 1 | 0 | 1 | inconclusive (fewer than 10 discordant cases) |

## Transitions

| Arm | Base outcome | Arm outcome | Items |
| --- | --- | --- | ---: |
| resample | invalid | invalid | 2 |
| resample | silent_wrong | invalid | 1 |
| resample | silent_wrong | silent_wrong | 4 |
| bare | invalid | invalid | 2 |
| bare | silent_wrong | malformed | 1 |
| bare | silent_wrong | silent_wrong | 3 |
| bare | silent_wrong | strong_exact | 1 |
| counterexample | invalid | silent_wrong | 2 |
| counterexample | silent_wrong | malformed | 1 |
| counterexample | silent_wrong | abstained | 1 |
| counterexample | silent_wrong | strong_exact | 3 |

## Items

| Item | Case | Base outcome | Base outcome now | Card | resample | bare | counterexample |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mei-0008 | dns-a-queries | invalid | invalid | error | invalid | invalid | silent_wrong |
| mei-0013 | ecn-syn-or-expiring | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | abstained |
| mei-0015 | aaaa-or-nxdomain | silent_wrong | silent_wrong | frames | silent_wrong | malformed | strong_exact |
| mei-0017 | reset-or-fin | invalid | invalid | error | invalid | invalid | silent_wrong |
| mei-0022 | private-destination | silent_wrong | silent_wrong | frames | silent_wrong | strong_exact | malformed |
| mei-0023 | dns-error-responses | silent_wrong | silent_wrong | frames | silent_wrong | silent_wrong | strong_exact |
| mei-0024 | dns-error-responses | silent_wrong | silent_wrong | frames | invalid | silent_wrong | strong_exact |

Base outcome changed since the plan: none.
