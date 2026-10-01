# Score summary

Model: mistralai/ministral-8b-2512. Split: dev. Run: dev-ministral-8b-2512-2026-09-26. Cases: 20, items: 160.
Gold hash: 6597c4d22cb9. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every ready-gold metric, drawn from 12 ready cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 40 | 0.542 [0.292, 0.792] | 0.458 [0.167, 0.750] | 0.083 [0.000, 0.208] | 0.154 (2/13) [0.000, 0.429] | 0.083 [0.000, 0.208] | 0 | 0 | 2 | n/a | 0.000088 | 1844 |
| C2 | 40 | 0.625 [0.375, 0.833] | 0.417 [0.208, 0.625] | 0.208 [0.042, 0.375] | 0.333 (5/15) [0.083, 0.600] | 0.083 [0.000, 0.208] | 0 | 0 | 2 | 0.639 full 0.458 at k<=16 | 0.000219 | 1703 |
| C3 | 40 | 0.500 [0.292, 0.708] | 0.375 [0.167, 0.625] | 0.125 [0.000, 0.250] | 0.250 (3/12) [0.000, 0.571] | 0.000 [0.000, 0.000] | 0 | 0 | 6 | n/a | 0.000134 | 2672 |
| C4 | 40 | 0.750 [0.542, 0.958] | 0.375 [0.125, 0.625] | 0.375 [0.125, 0.625] | 0.500 (9/18) [0.211, 0.800] | 0.000 [0.000, 0.000] | 0 | 0 | 3 | 0.639 full 0.458 at k<=16 | 0.000260 | 2656 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Items, Shortcut, Provider failed and Malformed count non-ready items too; every rate in this table covers ready gold only.
Intervals drawn from fewer than 1,000 resamples skip draws whose denominator is zero: C1 slot match 998; C2 slot match 998; C3 slot match 998; C4 slot match 998.
## Non-ready gold

| Condition | False-ready | Clarification | Not expressible | Slot match |
| --- | ---: | ---: | ---: | ---: |
| C1 | 0.188 [0.062, 0.375] | 0.375 [0.125, 0.500] | 0.000 [0.000, 0.000] | 0.625 [0.500, 0.875] |
| C2 | 0.250 [0.062, 0.500] | 0.000 [0.000, 0.000] | 0.500 [0.125, 0.900] | 1.000 [1.000, 1.000] |
| C3 | 0.312 [0.125, 0.500] | 0.375 [0.100, 0.500] | 0.250 [0.000, 0.500] | 0.250 [0.000, 0.500] |
| C4 | 0.125 [0.000, 0.312] | 0.000 [0.000, 0.000] | 0.250 [0.000, 0.500] | 1.000 [1.000, 1.000] |

Rates above this table cover ready gold only; these cover the 8 non-ready cases, resampled with their own index vectors.


## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C4 - C2 | strong exact | -0.042 [-0.208, 0.125] | 2 | 3 | 5 | inconclusive (fewer than 10 discordant cases) |
| C2 - C1 | strong exact | -0.042 [-0.333, 0.208] | 2 | 3 | 5 | inconclusive (fewer than 10 discordant cases) |
| C4 - C3 | strong exact | 0.000 [-0.125, 0.125] | 1 | 1 | 2 | inconclusive (fewer than 10 discordant cases) |

## Run settings

| Setting | Value |
| --- | --- |
| requested_model | mistralai/ministral-8b-2512 |
| served_models | mistralai/ministral-8b-2512 |
| served_models_distinct | 1 |
| served_model_changed | false |
| providers | Mistral |
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
| provider_order | mistral |
| allow_fallbacks | false |
| timeout_seconds | 120.0 |

## Spend

Price-derived USD: 0.0281. Provider reported USD: 0.0179. Charged upper bound: 0.0180.
Price-derived cost is above the charged upper bound, so the recorded prices and the recorded charge disagree.

## Notes

Not measured: repair_at_1 (not_run)

Files: summary.json, outcomes.jsonl, receipts/.
