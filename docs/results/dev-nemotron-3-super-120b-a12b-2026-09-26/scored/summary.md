# Score summary

Model: nvidia/nemotron-3-super-120b-a12b. Split: dev. Run: dev-nemotron-3-super-120b-a12b-2026-09-26. Cases: 20, items: 160.
Gold hash: 6597c4d22cb9. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every ready-gold metric, drawn from 12 ready cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 40 | 0.667 [0.417, 0.875] | 0.458 [0.250, 0.667] | 0.208 [0.042, 0.417] | 0.312 (5/16) [0.077, 0.556] | 0.083 [0.000, 0.208] | 0 | 0 | 0 | n/a | 0.000066 | 1563 |
| C2 | 40 | 0.667 [0.458, 0.833] | 0.417 [0.167, 0.667] | 0.250 [0.125, 0.375] | 0.375 (6/16) [0.167, 0.647] | 0.167 [0.042, 0.292] | 0 | 0 | 0 | 0.639 full 0.458 at k<=16 | 0.000134 | 1562 |
| C3 | 40 | 0.333 [0.167, 0.500] | 0.292 [0.125, 0.458] | 0.042 [0.000, 0.125] | 0.125 (1/8) [0.000, 0.500] | 0.208 [0.083, 0.333] | 0 | 0 | 2 | n/a | 0.000115 | 2156 |
| C4 | 40 | 0.583 [0.333, 0.792] | 0.375 [0.125, 0.625] | 0.208 [0.042, 0.417] | 0.357 (5/14) [0.077, 0.706] | 0.250 [0.042, 0.500] | 0 | 0 | 0 | 0.639 full 0.458 at k<=16 | 0.000183 | 2344 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Items, Shortcut, Provider failed and Malformed count non-ready items too; every rate in this table covers ready gold only.
Intervals drawn from fewer than 1,000 resamples skip draws whose denominator is zero: C1 slot match 998; C2 slot match 998; C3 slot match 998; C4 slot match 998.
## Non-ready gold

| Condition | False-ready | Clarification | Not expressible | Slot match |
| --- | ---: | ---: | ---: | ---: |
| C1 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |
| C2 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.750 [0.250, 1.000] |
| C3 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |
| C4 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.750 [0.250, 1.000] |

Rates above this table cover ready gold only; these cover the 8 non-ready cases, resampled with their own index vectors.


## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C4 - C2 | strong exact | -0.042 [-0.250, 0.167] | 2 | 2 | 4 | inconclusive (fewer than 10 discordant cases) |
| C2 - C1 | strong exact | -0.042 [-0.333, 0.208] | 2 | 3 | 5 | inconclusive (fewer than 10 discordant cases) |
| C4 - C3 | strong exact | 0.083 [-0.208, 0.375] | 4 | 2 | 6 | inconclusive (fewer than 10 discordant cases) |

## Run settings

| Setting | Value |
| --- | --- |
| requested_model | nvidia/nemotron-3-super-120b-a12b |
| served_models | nvidia/nemotron-3-super-120b-a12b |
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

Price-derived USD: 0.0200. Provider reported USD: 0.0200. Charged upper bound: 0.0200.

## Notes

Not measured: repair_at_1 (not_run)

Files: summary.json, outcomes.jsonl, receipts/.
