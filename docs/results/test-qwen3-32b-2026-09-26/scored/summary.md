# Score summary

Model: qwen/qwen3-32b. Split: test. Run: test-qwen3-32b-2026-09-26. Cases: 56, items: 448.
Gold hash: a9632daadafe. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every ready-gold metric, drawn from 40 ready cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 112 | 0.688 [0.550, 0.812] | 0.637 [0.500, 0.775] | 0.050 [0.013, 0.100] | 0.073 (4/55) [0.016, 0.148] | 0.050 [0.000, 0.125] | 0 | 0 | 0 | n/a | 0.000054 | 3704 |
| C2 | 112 | 0.750 [0.650, 0.850] | 0.575 [0.438, 0.713] | 0.175 [0.087, 0.263] | 0.233 (14/60) [0.107, 0.375] | 0.125 [0.050, 0.212] | 0 | 0 | 0 | 0.592 full 0.350 at k<=16 | 0.000110 | 4157 |
| C3 | 112 | 0.675 [0.537, 0.800] | 0.600 [0.450, 0.738] | 0.075 [0.013, 0.150] | 0.111 (6/54) [0.018, 0.227] | 0.000 [0.000, 0.000] | 0 | 0 | 0 | n/a | 0.000102 | 6922 |
| C4 | 112 | 0.812 [0.725, 0.887] | 0.500 [0.375, 0.613] | 0.312 [0.200, 0.438] | 0.385 (25/65) [0.247, 0.530] | 0.037 [0.000, 0.087] | 0 | 0 | 9 | 0.592 full 0.350 at k<=16 | 0.000163 | 7453 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Items, Shortcut, Provider failed and Malformed count non-ready items too; every rate in this table covers ready gold only.
## Non-ready gold

| Condition | False-ready | Clarification | Not expressible | Slot match |
| --- | ---: | ---: | ---: | ---: |
| C1 | 0.031 [0.000, 0.094] | 0.000 [0.000, 0.000] | 0.062 [0.000, 0.214] | 1.000 [1.000, 1.000] |
| C2 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.938 [0.800, 1.000] |
| C3 | 0.125 [0.000, 0.281] | 0.062 [0.000, 0.200] | 0.188 [0.000, 0.500] | 0.875 [0.714, 1.000] |
| C4 | 0.156 [0.062, 0.281] | 0.125 [0.000, 0.286] | 0.188 [0.000, 0.364] | 0.750 [0.500, 1.000] |

Rates above this table cover ready gold only; these cover the 16 non-ready cases, resampled with their own index vectors.


## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C4 - C2 | strong exact | -0.075 [-0.225, 0.062] | 10 | 11 | 21 | conclusive |
| C2 - C1 | strong exact | -0.062 [-0.188, 0.062] | 5 | 7 | 12 | conclusive |
| C4 - C3 | strong exact | -0.100 [-0.250, 0.062] | 8 | 13 | 21 | conclusive |

## Run settings

| Setting | Value |
| --- | --- |
| requested_model | qwen/qwen3-32b |
| served_models | qwen/qwen3-32b |
| served_models_distinct | 1 |
| served_model_changed | false |
| providers | DeepInfra |
| providers_distinct | 1 |
| provider_changed | false |
| system_fingerprints | - |
| system_fingerprints_distinct | 0 |
| reasoning_tokens_total | 0 |
| items_with_reasoning | 0 |
| thinking | honoured |
| thinking_evidence_items | 448 |
| seed_requested | 17 |
| seed | uncontrolled |
| temperature | 0.0 |
| max_output_tokens | 2048 |
| json_mode | true |
| provider_order | deepinfra |
| allow_fallbacks | false |
| timeout_seconds | 120.0 |

## Spend

Price-derived USD: 0.0481. Provider reported USD: 0.0481. Charged upper bound: 0.0483.

## Notes

Not measured: repair_at_1 (not_run)

Files: summary.json, outcomes.jsonl, receipts/.
