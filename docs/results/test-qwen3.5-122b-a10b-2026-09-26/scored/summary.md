# Score summary

Model: qwen/qwen3.5-122b-a10b. Split: test. Run: test-qwen3.5-122b-a10b-2026-09-26. Cases: 56, items: 448.
Gold hash: a9632daadafe. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every ready-gold metric, drawn from 40 ready cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 112 | 0.762 [0.650, 0.863] | 0.700 [0.588, 0.812] | 0.050 [0.013, 0.100] | 0.066 (4/61) [0.016, 0.130] | 0.087 [0.013, 0.175] | 1 | 0 | 0 | n/a | 0.000549 | 1703 |
| C2 | 112 | 0.825 [0.725, 0.900] | 0.675 [0.562, 0.775] | 0.150 [0.062, 0.250] | 0.182 (12/66) [0.078, 0.290] | 0.050 [0.013, 0.100] | 0 | 0 | 0 | 0.592 full 0.350 at k<=16 | 0.000794 | 1625 |
| C3 | 112 | 0.838 [0.738, 0.925] | 0.738 [0.637, 0.850] | 0.100 [0.037, 0.175] | 0.119 (8/67) [0.044, 0.208] | 0.075 [0.013, 0.163] | 0 | 0 | 1 | n/a | 0.000948 | 2281 |
| C4 | 112 | 0.800 [0.688, 0.900] | 0.613 [0.475, 0.738] | 0.175 [0.087, 0.275] | 0.219 (14/64) [0.108, 0.339] | 0.062 [0.013, 0.113] | 1 | 0 | 5 | 0.592 full 0.350 at k<=16 | 0.001267 | 2266 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Items, Shortcut, Provider failed and Malformed count non-ready items too; every rate in this table covers ready gold only.
## Non-ready gold

| Condition | False-ready | Clarification | Not expressible | Slot match |
| --- | ---: | ---: | ---: | ---: |
| C1 | 0.062 [0.000, 0.188] | 0.000 [0.000, 0.000] | 0.125 [0.000, 0.429] | 1.000 [1.000, 1.000] |
| C2 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |
| C3 | 0.062 [0.000, 0.188] | 0.000 [0.000, 0.000] | 0.125 [0.000, 0.429] | 1.000 [1.000, 1.000] |
| C4 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |

Rates above this table cover ready gold only; these cover the 16 non-ready cases, resampled with their own index vectors.


## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C4 - C2 | strong exact | -0.062 [-0.188, 0.062] | 7 | 11 | 18 | conclusive |
| C2 - C1 | strong exact | -0.025 [-0.138, 0.087] | 7 | 10 | 17 | conclusive |
| C4 - C3 | strong exact | -0.125 [-0.263, 0.000] | 5 | 14 | 19 | conclusive |

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
| thinking_evidence_items | 448 |
| seed_requested | 17 |
| seed | uncontrolled |
| temperature | 0.0 |
| max_output_tokens | 2048 |
| json_mode | true |
| provider_order | novita |
| allow_fallbacks | false |
| timeout_seconds | 120.0 |

## Spend

Price-derived USD: 0.3986. Provider reported USD: 0.3986. Charged upper bound: 0.3988.

## Notes

Not measured: repair_at_1 (not_run)

Files: summary.json, outcomes.jsonl, receipts/.
