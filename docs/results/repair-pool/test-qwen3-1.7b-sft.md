# Repair pool

Split: test. Bases: 3. Each drawn case brings every model's cells.
Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, drawn from 40 ready cases shared by every base.

## Bases

| Run | Model | Triggered items | Triggered cases | Summary |
| --- | --- | ---: | ---: | --- |
| test-qwen3-1.7b-sft-s17-2026-10-07 | qwen3-1.7b-sft-s17 | 45 | 31 | d4e2c1571d52 |
| test-qwen3-1.7b-sft-s2026-2026-10-07 | qwen3-1.7b-sft-s2026 | 36 | 26 | 4a9dd7b6a8af |
| test-qwen3-1.7b-sft-s42-2026-10-07 | qwen3-1.7b-sft-s42 | 44 | 30 | bd618900ebb9 |

## Arms

| Arm | repair@1 | Repaired |
| --- | ---: | ---: |
| resample | 0.008 [0.000, 0.028] | 1/125 |
| bare | 0.016 [0.000, 0.041] | 2/125 |
| counterexample | 0.000 [0.000, 0.000] | 0/125 |

## Comparisons

| Comparison | Difference | First better | Second better | Discordant | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| counterexample - bare | -0.016 [-0.041, 0.000] | 0 | 2 | 2 | inconclusive (fewer than 10 discordant cases) |
| counterexample - resample | -0.008 [-0.029, 0.000] | 0 | 1 | 1 | inconclusive (fewer than 10 discordant cases) |
| bare - resample | 0.008 [-0.019, 0.036] | 2 | 1 | 3 | inconclusive (fewer than 10 discordant cases) |
