# Score summary

Model: qwen/qwen3-32b. Split: test. Run: test-qwen3-32b-passb-2026-09-26. Cases: 56, items: 448.
Gold hash: a9632daadafe. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every ready-gold metric, drawn from 40 ready cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 112 | 0.662 [0.525, 0.787] | 0.600 [0.463, 0.738] | 0.062 [0.013, 0.113] | 0.094 (5/53) [0.019, 0.182] | 0.037 [0.000, 0.100] | 0 | 0 | 1 | n/a | 0.000059 | 4016 |
| C2 | 112 | 0.725 [0.613, 0.838] | 0.562 [0.412, 0.700] | 0.163 [0.075, 0.263] | 0.224 (13/58) [0.107, 0.360] | 0.125 [0.050, 0.212] | 0 | 0 | 0 | 0.592 full 0.350 at k<=16 | 0.000110 | 4079 |
| C3 | 112 | 0.700 [0.575, 0.825] | 0.637 [0.500, 0.762] | 0.062 [0.013, 0.125] | 0.089 (5/56) [0.018, 0.192] | 0.013 [0.000, 0.037] | 0 | 0 | 3 | n/a | 0.000107 | 7031 |
| C4 | 112 | 0.812 [0.725, 0.887] | 0.500 [0.375, 0.613] | 0.300 [0.188, 0.412] | 0.369 (24/65) [0.238, 0.493] | 0.037 [0.000, 0.087] | 1 | 0 | 8 | 0.592 full 0.350 at k<=16 | 0.000162 | 7063 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Items, Shortcut, Provider failed and Malformed count non-ready items too; every rate in this table covers ready gold only.
## Non-ready gold

| Condition | False-ready | Clarification | Not expressible | Slot match |
| --- | ---: | ---: | ---: | ---: |
| C1 | 0.031 [0.000, 0.094] | 0.000 [0.000, 0.000] | 0.062 [0.000, 0.214] | 1.000 [1.000, 1.000] |
| C2 | 0.031 [0.000, 0.094] | 0.062 [0.000, 0.200] | 0.000 [0.000, 0.000] | 0.938 [0.800, 1.000] |
| C3 | 0.125 [0.000, 0.281] | 0.062 [0.000, 0.200] | 0.188 [0.000, 0.500] | 0.812 [0.625, 1.000] |
| C4 | 0.125 [0.031, 0.219] | 0.125 [0.000, 0.286] | 0.125 [0.000, 0.286] | 0.688 [0.375, 1.000] |

Rates above this table cover ready gold only; these cover the 16 non-ready cases, resampled with their own index vectors.


## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C4 - C2 | strong exact | -0.062 [-0.212, 0.075] | 10 | 13 | 23 | conclusive |
| C2 - C1 | strong exact | -0.037 [-0.138, 0.062] | 5 | 6 | 11 | conclusive |
| C4 - C3 | strong exact | -0.138 [-0.275, 0.000] | 6 | 15 | 21 | conclusive |

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
| thinking_evidence_items | 448 |
| seed_requested | 17 |
| seed | uncontrolled |
| temperature | 0.0 |
| max_output_tokens | 2048 |
| json_mode | true |
| provider_order | deepinfra |
| allow_fallbacks | false |
| timeout_seconds | 120.0 |

## Spend

Price-derived USD: 0.0491. Provider reported USD: 0.0491. Charged upper bound: 0.0493.

## Notes

Not measured: repair_at_1 (not_run)

Files: summary.json, outcomes.jsonl, receipts/.
