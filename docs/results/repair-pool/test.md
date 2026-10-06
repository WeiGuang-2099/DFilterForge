# Repair pool

Split: test. Bases: 4. Each drawn case brings every model's cells.
Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, drawn from 40 ready cases shared by every base.

## Bases

| Run | Model | Triggered items | Triggered cases | Summary |
| --- | --- | ---: | ---: | --- |
| test-deepseek-v4-pro-0813-2026-09-26 | deepseek/deepseek-v4-pro-0813 | 12 | 9 | 25267047a417 |
| test-qwen3-32b-2026-09-26 | qwen/qwen3-32b | 28 | 20 | ce966aafcbf3 |
| test-qwen3.5-122b-a10b-2026-09-26 | qwen/qwen3.5-122b-a10b | 20 | 16 | 16f5cee240f5 |
| test-qwen3.5-9b-2026-09-26 | qwen/qwen3.5-9b | 15 | 11 | 508fc4595af4 |

## Arms

| Arm | repair@1 | Repaired |
| --- | ---: | ---: |
| resample | 0.053 [0.014, 0.113] | 4/75 |
| bare | 0.280 [0.161, 0.435] | 21/75 |
| counterexample | 0.467 [0.347, 0.590] | 35/75 |

## Comparisons

| Comparison | Difference | First better | Second better | Discordant | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| counterexample - bare | 0.187 [0.056, 0.301] | 12 | 4 | 16 | conclusive |
| counterexample - resample | 0.413 [0.277, 0.537] | 21 | 2 | 23 | conclusive |
| bare - resample | 0.227 [0.115, 0.369] | 13 | 0 | 13 | conclusive |
