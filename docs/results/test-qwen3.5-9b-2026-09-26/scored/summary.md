# Score summary

Model: qwen/qwen3.5-9b. Split: test. Run: test-qwen3.5-9b-2026-09-26. Cases: 56, items: 448.
Gold hash: a9632daadafe. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every ready-gold metric, drawn from 40 ready cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 112 | 0.700 [0.588, 0.800] | 0.550 [0.438, 0.675] | 0.150 [0.075, 0.225] | 0.214 (12/56) [0.113, 0.327] | 0.025 [0.000, 0.062] | 0 | 0 | 7 | n/a | 0.000076 | 13094 |
| C2 | 112 | 0.713 [0.613, 0.812] | 0.537 [0.425, 0.662] | 0.175 [0.087, 0.275] | 0.246 (14/57) [0.127, 0.379] | 0.150 [0.075, 0.237] | 0 | 0 | 1 | 0.592 full 0.350 at k<=16 | 0.000127 | 11922 |
| C3 | 112 | 0.575 [0.463, 0.688] | 0.400 [0.275, 0.525] | 0.175 [0.087, 0.263] | 0.304 (14/46) [0.163, 0.450] | 0.113 [0.037, 0.200] | 0 | 0 | 12 | n/a | 0.000107 | 18485 |
| C4 | 112 | 0.575 [0.450, 0.700] | 0.438 [0.325, 0.550] | 0.138 [0.062, 0.225] | 0.239 (11/46) [0.116, 0.378] | 0.287 [0.188, 0.400] | 0 | 4 | 7 | 0.592 full 0.350 at k<=16 | 0.000162 | 17203 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Items, Shortcut, Provider failed and Malformed count non-ready items too; every rate in this table covers ready gold only.
Latency p50 covers completed items only; 4 provider failures are excluded and counted in the Provider failed column.
Cost USD/item is derived from recorded token counts and the prices in the run manifest; it is a lower bound where usage was missing.
## Non-ready gold

| Condition | False-ready | Clarification | Not expressible | Slot match |
| --- | ---: | ---: | ---: | ---: |
| C1 | 0.125 [0.031, 0.250] | 0.125 [0.000, 0.300] | 0.125 [0.000, 0.286] | 0.688 [0.375, 1.000] |
| C2 | 0.031 [0.000, 0.094] | 0.062 [0.000, 0.200] | 0.000 [0.000, 0.000] | 0.812 [0.500, 1.000] |
| C3 | 0.062 [0.000, 0.156] | 0.000 [0.000, 0.000] | 0.125 [0.000, 0.286] | 0.750 [0.438, 1.000] |
| C4 | 0.031 [0.000, 0.094] | 0.062 [0.000, 0.200] | 0.000 [0.000, 0.000] | 0.750 [0.400, 1.000] |

Rates above this table cover ready gold only; these cover the 16 non-ready cases, resampled with their own index vectors.


## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C4 - C2 | strong exact | -0.100 [-0.237, 0.037] | 7 | 13 | 20 | conclusive |
| C2 - C1 | strong exact | -0.013 [-0.125, 0.113] | 8 | 11 | 19 | conclusive |
| C4 - C3 | strong exact | 0.037 [-0.075, 0.150] | 8 | 8 | 16 | conclusive |

## Run settings

| Setting | Value |
| --- | --- |
| requested_model | qwen/qwen3.5-9b |
| served_models | qwen/qwen3.5-9b |
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
| thinking_evidence_items | 444 |
| seed_requested | 17 |
| seed | uncontrolled |
| temperature | 0.0 |
| max_output_tokens | 2048 |
| json_mode | true |
| provider_order | deepinfra |
| allow_fallbacks | false |
| timeout_seconds | 120.0 |

## Spend

Price-derived USD: 0.0528. Provider reported USD: 0.0528. Charged upper bound: 0.0530.
Price-derived cost is a lower bound: usage was missing for 4 items and 139 items spent tokens on a retry.

## Notes

Not measured: repair_at_1 (not_run)

Files: summary.json, outcomes.jsonl, receipts/.
