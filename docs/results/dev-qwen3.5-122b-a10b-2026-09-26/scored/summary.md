# Score summary

Model: qwen/qwen3.5-122b-a10b. Split: dev. Run: dev-qwen3.5-122b-a10b-2026-09-26. Cases: 20, items: 160.
Gold hash: 6597c4d22cb9. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every ready-gold metric, drawn from 12 ready cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 40 | 0.625 [0.417, 0.833] | 0.583 [0.333, 0.792] | 0.042 [0.000, 0.125] | 0.067 (1/15) [0.000, 0.273] | 0.125 [0.000, 0.250] | 0 | 0 | 0 | n/a | 0.000502 | 1922 |
| C2 | 40 | 0.708 [0.458, 0.917] | 0.583 [0.333, 0.833] | 0.125 [0.000, 0.333] | 0.176 (3/17) [0.000, 0.450] | 0.125 [0.000, 0.292] | 0 | 0 | 0 | 0.639 full 0.458 at k<=16 | 0.000756 | 1890 |
| C3 | 40 | 0.792 [0.625, 0.958] | 0.750 [0.542, 0.917] | 0.042 [0.000, 0.125] | 0.053 (1/19) [0.000, 0.174] | 0.042 [0.000, 0.125] | 0 | 0 | 2 | n/a | 0.000799 | 2156 |
| C4 | 40 | 0.750 [0.625, 0.875] | 0.458 [0.167, 0.708] | 0.292 [0.167, 0.417] | 0.389 (7/18) [0.190, 0.714] | 0.125 [0.000, 0.250] | 0 | 0 | 2 | 0.639 full 0.458 at k<=16 | 0.001083 | 2156 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Items, Shortcut, Provider failed and Malformed count non-ready items too; every rate in this table covers ready gold only.
Intervals drawn from fewer than 1,000 resamples skip draws whose denominator is zero: C1 slot match 998; C2 slot match 998; C3 slot match 998; C4 slot match 998.
## Non-ready gold

| Condition | False-ready | Clarification | Not expressible | Slot match |
| --- | ---: | ---: | ---: | ---: |
| C1 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |
| C2 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |
| C3 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |
| C4 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |

Rates above this table cover ready gold only; these cover the 8 non-ready cases, resampled with their own index vectors.


## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C4 - C2 | strong exact | -0.125 [-0.333, 0.042] | 1 | 3 | 4 | inconclusive (fewer than 10 discordant cases) |
| C2 - C1 | strong exact | 0.000 [-0.333, 0.375] | 5 | 4 | 9 | inconclusive (fewer than 10 discordant cases) |
| C4 - C3 | strong exact | -0.292 [-0.583, 0.000] | 2 | 6 | 8 | inconclusive (fewer than 10 discordant cases) |

## Run settings

| Setting | Value |
| --- | --- |
| requested_model | qwen/qwen3.5-122b-a10b |
| served_models | qwen/qwen3.5-122b-a10b |
| served_models_distinct | 1 |
| served_model_changed | false |
| providers | Novita |
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
| provider_order | novita |
| allow_fallbacks | false |
| timeout_seconds | 120.0 |

## Spend

Price-derived USD: 0.1256. Provider reported USD: 0.1256. Charged upper bound: 0.1257.
Price-derived cost is a lower bound: 70 items spent tokens on a retry.

## Notes

Not measured: repair_at_1 (not_run)

Files: summary.json, outcomes.jsonl, receipts/.
