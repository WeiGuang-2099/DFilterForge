# Score summary

Model: Qwen/Qwen3-1.7B. Split: test. Run: test-qwen3-1.7b-schema-ord-2026-10-26. Cases: 56, items: 112.
Gold hash: a9632daadafe. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every ready-gold metric, drawn from 40 ready cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C4 | 112 | 0.463 [0.338, 0.588] | 0.087 [0.025, 0.163] | 0.375 [0.263, 0.487] | 0.811 (30/37) [0.667, 0.935] | 0.000 [0.000, 0.000] | 0 | 1 | 10 | 0.592 full 0.350 at k<=16 | 0.000017 | 4469 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Items, Shortcut, Provider failed and Malformed count non-ready items too; every rate in this table covers ready gold only.
Latency p50 covers completed items only; 1 provider failure is excluded and counted in the Provider failed column.
Cost USD/item is derived from recorded token counts and the prices in the run manifest; it is a lower bound where usage was missing.
## Non-ready gold

| Condition | False-ready | Clarification | Not expressible | Slot match |
| --- | ---: | ---: | ---: | ---: |
| C4 | 0.938 [0.844, 1.000] | 0.938 [0.800, 1.000] | 0.938 [0.800, 1.000] | 0.000 [0.000, 0.000] |

Rates above this table cover ready gold only; these cover the 16 non-ready cases, resampled with their own index vectors.


## Run settings

| Setting | Value |
| --- | --- |
| requested_model | Qwen/Qwen3-1.7B |
| served_models | Qwen/Qwen3-1.7B |
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
| thinking_evidence_items | 111 |
| seed_requested | 17 |
| seed | uncontrolled |
| temperature | 0.0 |
| max_output_tokens | 2048 |
| json_mode | true |
| provider_order | - |
| allow_fallbacks | n/a |
| timeout_seconds | 120.0 |

## Spend

Price-derived USD: 0.0019. Provider reported USD: n/a. Charged upper bound: 0.0020.
Price-derived cost is a lower bound: usage was missing for 1 item.

## Notes

Not measured: C2-C1 (condition_not_run); C4-C2 (condition_not_run); C4-C3 (condition_not_run); repair_at_1 (not_run)

Files: summary.json, outcomes.jsonl, receipts/.
