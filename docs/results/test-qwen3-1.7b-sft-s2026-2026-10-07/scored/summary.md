# Score summary

Model: qwen3-1.7b-sft-s2026. Split: test. Run: test-qwen3-1.7b-sft-s2026-2026-10-07. Cases: 56, items: 448.
Gold hash: a9632daadafe. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every ready-gold metric, drawn from 40 ready cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 112 | 0.562 [0.425, 0.688] | 0.287 [0.175, 0.412] | 0.275 [0.163, 0.388] | 0.489 (22/45) [0.318, 0.660] | 0.113 [0.050, 0.188] | 0 | 0 | 2 | n/a | 0.000004 | 1843 |
| C2 | 112 | 0.525 [0.388, 0.650] | 0.237 [0.113, 0.350] | 0.287 [0.163, 0.412] | 0.548 (23/42) [0.349, 0.744] | 0.175 [0.087, 0.263] | 0 | 0 | 3 | 0.592 full 0.350 at k<=16 | 0.000011 | 1906 |
| C3 | 112 | 0.688 [0.588, 0.775] | 0.350 [0.250, 0.463] | 0.338 [0.225, 0.450] | 0.491 (27/55) [0.340, 0.630] | 0.050 [0.013, 0.100] | 0 | 0 | 9 | n/a | 0.000007 | 2672 |
| C4 | 112 | 0.787 [0.675, 0.887] | 0.475 [0.338, 0.600] | 0.312 [0.200, 0.438] | 0.397 (25/63) [0.258, 0.544] | 0.037 [0.000, 0.087] | 0 | 0 | 5 | 0.592 full 0.350 at k<=16 | 0.000014 | 2734 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Items, Shortcut, Provider failed and Malformed count non-ready items too; every rate in this table covers ready gold only.
## Non-ready gold

| Condition | False-ready | Clarification | Not expressible | Slot match |
| --- | ---: | ---: | ---: | ---: |
| C1 | 0.281 [0.125, 0.469] | 0.250 [0.071, 0.429] | 0.312 [0.000, 0.643] | 0.500 [0.167, 0.800] |
| C2 | 0.156 [0.000, 0.344] | 0.000 [0.000, 0.000] | 0.312 [0.000, 0.643] | 0.812 [0.500, 1.000] |
| C3 | 0.281 [0.094, 0.500] | 0.188 [0.000, 0.375] | 0.375 [0.000, 0.714] | 0.562 [0.250, 0.833] |
| C4 | 0.188 [0.031, 0.375] | 0.062 [0.000, 0.214] | 0.312 [0.000, 0.625] | 0.938 [0.786, 1.000] |

Rates above this table cover ready gold only; these cover the 16 non-ready cases, resampled with their own index vectors.


## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C4 - C2 | strong exact | 0.237 [0.100, 0.388] | 18 | 4 | 22 | conclusive |
| C2 - C1 | strong exact | -0.050 [-0.150, 0.050] | 4 | 8 | 12 | conclusive |
| C4 - C3 | strong exact | 0.125 [0.037, 0.212] | 11 | 2 | 13 | conclusive |

## Run settings

| Setting | Value |
| --- | --- |
| requested_model | qwen3-1.7b-sft-s2026 |
| served_models | qwen3-1.7b-sft-s2026 |
| served_models_distinct | 1 |
| served_model_changed | false |
| providers | - |
| providers_distinct | 0 |
| provider_changed | false |
| system_fingerprints | vllm-0.21.0-84f508c7 |
| system_fingerprints_distinct | 1 |
| reasoning_tokens_total | 0 |
| items_with_reasoning | 0 |
| thinking | uncontrolled |
| thinking_evidence_items | 448 |
| seed_requested | 17 |
| seed | uncontrolled |
| temperature | 0.0 |
| max_output_tokens | 2048 |
| json_mode | true |
| provider_order | - |
| allow_fallbacks | n/a |
| timeout_seconds | 120.0 |

## Spend

Price-derived USD: 0.0039. Provider reported USD: n/a. Charged upper bound: 0.0041.

## Notes

Not measured: repair_at_1 (not_run)

Files: summary.json, outcomes.jsonl, receipts/.
