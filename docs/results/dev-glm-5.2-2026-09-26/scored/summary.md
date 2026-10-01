# Score summary

Model: z-ai/glm-5.2. Split: dev. Run: dev-glm-5.2-2026-09-26. Cases: 20, items: 160.
Gold hash: 6597c4d22cb9. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every ready-gold metric, drawn from 12 ready cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 40 | 0.875 [0.667, 1.000] | 0.833 [0.625, 1.000] | 0.042 [0.000, 0.125] | 0.048 (1/21) [0.000, 0.150] | 0.000 [0.000, 0.000] | 0 | 0 | 0 | n/a | 0.000554 | 2422 |
| C2 | 40 | 0.958 [0.875, 1.000] | 0.792 [0.667, 0.917] | 0.167 [0.042, 0.292] | 0.174 (4/23) [0.043, 0.304] | 0.000 [0.000, 0.000] | 0 | 0 | 0 | 0.639 full 0.458 at k<=16 | 0.001214 | 2360 |
| C3 | 40 | 0.792 [0.583, 0.958] | 0.625 [0.333, 0.875] | 0.167 [0.000, 0.375] | 0.211 (4/19) [0.000, 0.500] | 0.000 [0.000, 0.000] | 0 | 1 | 1 | n/a | 0.000966 | 2829 |
| C4 | 40 | 0.792 [0.583, 0.958] | 0.750 [0.500, 0.958] | 0.042 [0.000, 0.125] | 0.053 (1/19) [0.000, 0.200] | 0.125 [0.042, 0.250] | 0 | 0 | 0 | 0.639 full 0.458 at k<=16 | 0.001580 | 2578 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Items, Shortcut, Provider failed and Malformed count non-ready items too; every rate in this table covers ready gold only.
Latency p50 covers completed items only; 1 provider failure is excluded and counted in the Provider failed column.
Intervals drawn from fewer than 1,000 resamples skip draws whose denominator is zero: C1 slot match 998; C2 slot match 998; C3 slot match 998; C4 slot match 998.
## Non-ready gold

| Condition | False-ready | Clarification | Not expressible | Slot match |
| --- | ---: | ---: | ---: | ---: |
| C1 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |
| C2 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |
| C3 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |
| C4 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.875 [0.625, 1.000] |

Rates above this table cover ready gold only; these cover the 8 non-ready cases, resampled with their own index vectors.


## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C4 - C2 | strong exact | -0.042 [-0.250, 0.167] | 3 | 4 | 7 | inconclusive (fewer than 10 discordant cases) |
| C2 - C1 | strong exact | -0.042 [-0.250, 0.167] | 3 | 4 | 7 | inconclusive (fewer than 10 discordant cases) |
| C4 - C3 | strong exact | 0.125 [-0.208, 0.417] | 4 | 2 | 6 | inconclusive (fewer than 10 discordant cases) |

## Run settings

| Setting | Value |
| --- | --- |
| requested_model | z-ai/glm-5.2 |
| served_models | z-ai/glm-5.2 |
| served_models_distinct | 1 |
| served_model_changed | false |
| providers | Alibaba |
| providers_distinct | 1 |
| provider_changed | false |
| system_fingerprints | - |
| system_fingerprints_distinct | 0 |
| reasoning_tokens_total | 0 |
| items_with_reasoning | 0 |
| thinking | honoured |
| thinking_evidence_items | 159 |
| seed_requested | 17 |
| seed | uncontrolled |
| temperature | 0.0 |
| max_output_tokens | 2048 |
| json_mode | true |
| provider_order | alibaba/fp8 |
| allow_fallbacks | false |
| timeout_seconds | 120.0 |

## Spend

Price-derived USD: 0.1726. Provider reported USD: 0.1454. Charged upper bound: 0.1455.
Price-derived cost is a lower bound: 35 items spent tokens on a retry.
Price-derived cost is above the charged upper bound, so the recorded prices and the recorded charge disagree.

## Notes

Not measured: repair_at_1 (not_run)

Files: summary.json, outcomes.jsonl, receipts/.
