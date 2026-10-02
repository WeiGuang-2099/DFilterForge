# Score summary

Model: deepseek/deepseek-v4-pro-0813. Split: test. Run: test-deepseek-v4-pro-0813-2026-09-26. Cases: 56, items: 448.
Gold hash: a9632daadafe. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every ready-gold metric, drawn from 40 ready cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 112 | 0.688 [0.562, 0.800] | 0.625 [0.500, 0.738] | 0.062 [0.013, 0.113] | 0.091 (5/55) [0.020, 0.170] | 0.000 [0.000, 0.000] | 0 | 21 | 2 | n/a | 0.000558 | 2375 |
| C2 | 112 | 0.912 [0.825, 0.988] | 0.762 [0.637, 0.875] | 0.150 [0.062, 0.250] | 0.164 (12/73) [0.070, 0.269] | 0.000 [0.000, 0.000] | 0 | 0 | 1 | 0.592 full 0.350 at k<=16 | 0.001634 | 2078 |
| C3 | 112 | 0.925 [0.850, 0.988] | 0.850 [0.750, 0.938] | 0.075 [0.025, 0.150] | 0.081 (6/74) [0.026, 0.164] | 0.000 [0.000, 0.000] | 0 | 0 | 1 | n/a | 0.001150 | 2609 |
| C4 | 112 | 0.900 [0.812, 0.975] | 0.850 [0.750, 0.938] | 0.050 [0.013, 0.100] | 0.056 (4/72) [0.014, 0.111] | 0.000 [0.000, 0.000] | 0 | 1 | 0 | 0.592 full 0.350 at k<=16 | 0.002139 | 2657 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Items, Shortcut, Provider failed and Malformed count non-ready items too; every rate in this table covers ready gold only.
Latency p50 covers completed items only; 22 provider failures are excluded and counted in the Provider failed column.
Cost USD/item is derived from recorded token counts and the prices in the run manifest; it is a lower bound where usage was missing.
## Non-ready gold

| Condition | False-ready | Clarification | Not expressible | Slot match |
| --- | ---: | ---: | ---: | ---: |
| C1 | 0.125 [0.000, 0.281] | 0.062 [0.000, 0.200] | 0.188 [0.000, 0.450] | 0.875 [0.714, 1.000] |
| C2 | 0.125 [0.000, 0.281] | 0.062 [0.000, 0.200] | 0.188 [0.000, 0.500] | 0.875 [0.700, 1.000] |
| C3 | 0.188 [0.031, 0.375] | 0.062 [0.000, 0.200] | 0.312 [0.000, 0.625] | 0.875 [0.700, 1.000] |
| C4 | 0.188 [0.031, 0.375] | 0.062 [0.000, 0.200] | 0.312 [0.000, 0.643] | 0.750 [0.400, 1.000] |

Rates above this table cover ready gold only; these cover the 16 non-ready cases, resampled with their own index vectors.


## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C4 - C2 | strong exact | 0.087 [-0.013, 0.188] | 9 | 2 | 11 | conclusive |
| C2 - C1 | strong exact | 0.138 [0.013, 0.263] | 11 | 4 | 15 | conclusive |
| C4 - C3 | strong exact | 0.000 [-0.113, 0.125] | 6 | 7 | 13 | conclusive |

## Run settings

| Setting | Value |
| --- | --- |
| requested_model | deepseek/deepseek-v4-pro-0813 |
| served_models | deepseek/deepseek-v4-pro-0813 |
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
| thinking_evidence_items | 426 |
| seed_requested | 17 |
| seed | uncontrolled |
| temperature | 0.0 |
| max_output_tokens | 2048 |
| json_mode | true |
| provider_order | deepinfra |
| allow_fallbacks | false |
| timeout_seconds | 120.0 |

## Spend

Price-derived USD: 0.6138. Provider reported USD: 0.5471. Charged upper bound: 0.5473.
Price-derived cost is a lower bound: usage was missing for 22 items and 440 items spent tokens on a retry.
Price-derived cost is above the charged upper bound, so the recorded prices and the recorded charge disagree.

## Notes

Not measured: repair_at_1 (not_run)

Files: summary.json, outcomes.jsonl, receipts/.
