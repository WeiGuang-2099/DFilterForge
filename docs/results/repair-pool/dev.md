# Repair pool

Split: dev. Bases: 4. Each drawn case brings every model's cells.
Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, drawn from 12 ready cases shared by every base.

## Bases

| Run | Model | Triggered items | Triggered cases | Summary |
| --- | --- | ---: | ---: | --- |
| dev-deepseek-v4-pro-0813-2026-09-26 | deepseek/deepseek-v4-pro-0813 | 11 | 7 | aca5075b2293 |
| dev-qwen3-32b-2026-09-26 | qwen/qwen3-32b | 10 | 6 | f69f0ded0f7f |
| dev-qwen3.5-122b-a10b-2026-09-26 | qwen/qwen3.5-122b-a10b | 8 | 7 | d4bb1e5c9af4 |
| dev-qwen3.5-9b-2026-09-26 | qwen/qwen3.5-9b | 7 | 6 | e95af1631f56 |

## Arms

| Arm | repair@1 | Repaired |
| --- | ---: | ---: |
| resample | 0.083 [0.000, 0.259] | 3/36 |
| bare | 0.167 [0.050, 0.370] | 6/36 |
| counterexample | 0.528 [0.257, 0.788] | 19/36 |

## Comparisons

| Comparison | Difference | First better | Second better | Discordant | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| counterexample - bare | 0.361 [0.083, 0.632] | 13 | 2 | 15 | conclusive |
| counterexample - resample | 0.444 [0.150, 0.741] | 15 | 1 | 16 | conclusive |
| bare - resample | 0.083 [0.000, 0.178] | 4 | 1 | 5 | inconclusive (fewer than 10 discordant cells) |
