# Score summary

Model: qwen/qwen3-32b. Split: dev. Run: dev-qwen3-32b-2026-09-26. Cases: 20, items: 160.
Gold hash: 6597c4d22cb9. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every ready-gold metric, drawn from 12 ready cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 40 | 0.708 [0.500, 0.875] | 0.542 [0.292, 0.750] | 0.167 [0.000, 0.333] | 0.235 (4/17) [0.000, 0.526] | 0.042 [0.000, 0.125] | 0 | 0 | 0 | n/a | 0.000052 | 2672 |
| C2 | 40 | 0.750 [0.542, 0.917] | 0.583 [0.333, 0.792] | 0.167 [0.000, 0.375] | 0.222 (4/18) [0.000, 0.500] | 0.083 [0.000, 0.250] | 0 | 0 | 0 | 0.639 full 0.458 at k<=16 | 0.000107 | 2625 |
| C3 | 40 | 0.583 [0.375, 0.792] | 0.458 [0.250, 0.667] | 0.125 [0.000, 0.250] | 0.214 (3/14) [0.000, 0.444] | 0.000 [0.000, 0.000] | 0 | 0 | 1 | n/a | 0.000093 | 4500 |
| C4 | 40 | 0.750 [0.500, 0.958] | 0.500 [0.250, 0.708] | 0.250 [0.042, 0.500] | 0.333 (6/18) [0.091, 0.625] | 0.042 [0.000, 0.125] | 0 | 0 | 1 | 0.639 full 0.458 at k<=16 | 0.000146 | 5313 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Items, Shortcut, Provider failed and Malformed count non-ready items too; every rate in this table covers ready gold only.
Intervals drawn from fewer than 1,000 resamples skip draws whose denominator is zero: C1 slot match 998; C2 slot match 998; C3 slot match 998; C4 slot match 998.
## Non-ready gold

| Condition | False-ready | Clarification | Not expressible | Slot match |
| --- | ---: | ---: | ---: | ---: |
| C1 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |
| C2 | 0.062 [0.000, 0.188] | 0.000 [0.000, 0.000] | 0.125 [0.000, 0.400] | 1.000 [1.000, 1.000] |
| C3 | 0.062 [0.000, 0.188] | 0.125 [0.000, 0.500] | 0.000 [0.000, 0.000] | 0.875 [0.500, 1.000] |
| C4 | 0.250 [0.000, 0.500] | 0.125 [0.000, 0.500] | 0.375 [0.000, 0.875] | 0.625 [0.167, 1.000] |

Rates above this table cover ready gold only; these cover the 8 non-ready cases, resampled with their own index vectors.


## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C4 - C2 | strong exact | -0.083 [-0.292, 0.083] | 2 | 4 | 6 | inconclusive (fewer than 10 discordant cases) |
| C2 - C1 | strong exact | 0.042 [-0.292, 0.333] | 5 | 3 | 8 | inconclusive (fewer than 10 discordant cases) |
| C4 - C3 | strong exact | 0.042 [-0.208, 0.250] | 2 | 1 | 3 | inconclusive (fewer than 10 discordant cases) |

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
| thinking_evidence_items | 160 |
| seed_requested | 17 |
| seed | uncontrolled |
| temperature | 0.0 |
| max_output_tokens | 2048 |
| json_mode | true |
| provider_order | deepinfra |
| allow_fallbacks | false |
| timeout_seconds | 120.0 |

## Spend

Price-derived USD: 0.0159. Provider reported USD: 0.0159. Charged upper bound: 0.0160.

## Notes

Not measured: repair_at_1 (not_run)

Files: summary.json, outcomes.jsonl, receipts/.
