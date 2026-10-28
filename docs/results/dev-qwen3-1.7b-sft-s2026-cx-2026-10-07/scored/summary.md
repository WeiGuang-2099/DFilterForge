# Score summary

Model: qwen3-1.7b-sft-s2026. Split: dev. Run: dev-qwen3-1.7b-sft-s2026-cx-2026-10-07. Cases: 10, items: 15.
Gold hash: a3ca60e25b2b. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every metric, drawn from 10 cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C4 | 15 | 0.150 [0.000, 0.300] | 0.000 [0.000, 0.000] | 0.150 [0.000, 0.300] | 1.000 (3/3) [1.000, 1.000] | 0.600 [0.350, 0.800] | 0 | 0 | 3 | 0.708 full 0.500 at k<=16 | 0.000016 | 1843 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Intervals drawn from fewer than 1,000 resamples skip draws whose denominator is zero: C4 silent-wrong (exec) 972.

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
| thinking_evidence_items | 15 |
| seed_requested | 17 |
| seed | uncontrolled |
| temperature | 0.0 |
| max_output_tokens | 2048 |
| json_mode | true |
| provider_order | - |
| allow_fallbacks | n/a |
| timeout_seconds | 120.0 |

## Spend

Price-derived USD: 0.0002. Provider reported USD: n/a. Charged upper bound: 0.0002.

## Notes

Not measured: C2-C1 (condition_not_run); C4-C2 (condition_not_run); C4-C3 (condition_not_run); false_ready (no_non_ready_gold); repair_at_1 (not_run); slot_match (no_non_ready_gold)

Files: summary.json, outcomes.jsonl, receipts/.
