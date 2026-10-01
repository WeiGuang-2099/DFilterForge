# Score summary

Model: mistralai/mistral-medium-3-5. Split: dev. Run: dev-mistral-medium-3-5-2026-09-26. Cases: 20, items: 160.
Gold hash: 6597c4d22cb9. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every ready-gold metric, drawn from 12 ready cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 40 | 0.792 [0.583, 0.958] | 0.750 [0.500, 0.958] | 0.042 [0.000, 0.125] | 0.053 (1/19) [0.000, 0.176] | 0.000 [0.000, 0.000] | 0 | 0 | 0 | n/a | 0.001200 | 1328 |
| C2 | 40 | 0.833 [0.667, 1.000] | 0.625 [0.333, 0.875] | 0.208 [0.042, 0.417] | 0.250 (5/20) [0.053, 0.524] | 0.000 [0.000, 0.000] | 0 | 0 | 0 | 0.639 full 0.458 at k<=16 | 0.002427 | 1281 |
| C3 | 40 | 0.500 [0.250, 0.708] | 0.500 [0.250, 0.708] | 0.000 [0.000, 0.000] | 0.000 (0/12) [0.000, 0.000] | 0.000 [0.000, 0.000] | 0 | 8 | 0 | n/a | 0.001603 | 1469 |
| C4 | 40 | 0.333 [0.083, 0.583] | 0.250 [0.000, 0.500] | 0.083 [0.000, 0.250] | 0.250 (2/8) [0.000, 1.000] | 0.000 [0.000, 0.000] | 0 | 18 | 0 | 0.639 full 0.458 at k<=16 | 0.001725 | 1422 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Items, Shortcut, Provider failed and Malformed count non-ready items too; every rate in this table covers ready gold only.
Latency p50 covers completed items only; 26 provider failures are excluded and counted in the Provider failed column.
Cost USD/item is derived from recorded token counts and the prices in the run manifest; it is a lower bound where usage was missing.
Intervals drawn from fewer than 1,000 resamples skip draws whose denominator is zero: C1 slot match 998; C2 slot match 998; C3 slot match 998; C4 silent-wrong (exec) 993; C4 slot match 998.
## Non-ready gold

| Condition | False-ready | Clarification | Not expressible | Slot match |
| --- | ---: | ---: | ---: | ---: |
| C1 | 0.188 [0.000, 0.438] | 0.000 [0.000, 0.000] | 0.375 [0.000, 0.875] | 1.000 [1.000, 1.000] |
| C2 | 0.125 [0.000, 0.375] | 0.000 [0.000, 0.000] | 0.250 [0.000, 0.800] | 1.000 [1.000, 1.000] |
| C3 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |
| C4 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.750 [0.500, 1.000] |

Rates above this table cover ready gold only; these cover the 8 non-ready cases, resampled with their own index vectors.


## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C4 - C2 | strong exact | -0.375 [-0.625, -0.125] | 0 | 5 | 5 | inconclusive (fewer than 10 discordant cases) |
| C2 - C1 | strong exact | -0.125 [-0.333, 0.042] | 1 | 3 | 4 | inconclusive (fewer than 10 discordant cases) |
| C4 - C3 | strong exact | -0.250 [-0.583, 0.125] | 2 | 6 | 8 | inconclusive (fewer than 10 discordant cases) |

## Run settings

| Setting | Value |
| --- | --- |
| requested_model | mistralai/mistral-medium-3-5 |
| served_models | mistralai/mistral-medium-3-5 |
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
| thinking_evidence_items | 134 |
| seed_requested | 17 |
| seed | uncontrolled |
| temperature | 0.0 |
| max_output_tokens | 2048 |
| json_mode | true |
| provider_order | mistral |
| allow_fallbacks | false |
| timeout_seconds | 120.0 |

## Spend

Price-derived USD: 0.2782. Provider reported USD: 0.2529. Charged upper bound: 0.2530.
Price-derived cost is a lower bound: usage was missing for 26 items and 92 items spent tokens on a retry.
Price-derived cost is above the charged upper bound, so the recorded prices and the recorded charge disagree.

## Notes

Not measured: repair_at_1 (not_run)

Files: summary.json, outcomes.jsonl, receipts/.
