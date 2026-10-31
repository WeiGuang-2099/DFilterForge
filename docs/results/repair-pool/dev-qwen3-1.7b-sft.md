# Repair pool

Split: dev. Bases: 3. Each drawn case brings every model's cells.
Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, drawn from 12 ready cases shared by every base.

## Bases

| Run | Model | Triggered items | Triggered cases | Summary |
| --- | --- | ---: | ---: | --- |
| dev-qwen3-1.7b-sft-s17-2026-10-07 | qwen3-1.7b-sft-s17 | 14 | 9 | 446ff1542149 |
| dev-qwen3-1.7b-sft-s2026-2026-10-07 | qwen3-1.7b-sft-s2026 | 15 | 10 | 653f845657ba |
| dev-qwen3-1.7b-sft-s42-2026-10-07 | qwen3-1.7b-sft-s42 | 17 | 10 | 3439b0be74a9 |

## Arms

| Arm | repair@1 | Repaired |
| --- | ---: | ---: |
| resample | 0.000 [0.000, 0.000] | 0/46 |
| bare | 0.000 [0.000, 0.000] | 0/46 |
| counterexample | 0.000 [0.000, 0.000] | 0/46 |

## Comparisons

| Comparison | Difference | First better | Second better | Discordant | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| counterexample - bare | 0.000 [0.000, 0.000] | 0 | 0 | 0 | inconclusive (fewer than 10 discordant cases) |
| counterexample - resample | 0.000 [0.000, 0.000] | 0 | 0 | 0 | inconclusive (fewer than 10 discordant cases) |
| bare - resample | 0.000 [0.000, 0.000] | 0 | 0 | 0 | inconclusive (fewer than 10 discordant cases) |
