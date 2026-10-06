# Score summary

Model: deepseek/deepseek-v4-pro-0813. Split: test. Run: test-deepseek-v4-pro-0813-res-2026-09-26. Cases: 9, items: 12.
Gold hash: 2dec03cd6526. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every metric, drawn from 9 cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C4 | 12 | 0.500 [0.167, 0.778] | 0.167 [0.000, 0.389] | 0.333 [0.000, 0.667] | 0.667 (3/5) [0.000, 1.000] | 0.000 [0.000, 0.000] | 0 | 0 | 1 | 0.602 full 0.222 at k<=16 | 0.002307 | 4610 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Intervals drawn from fewer than 1,000 resamples skip draws whose denominator is zero: C4 silent-wrong (exec) 998.

## Run settings

| Setting | Value |
| --- | --- |
| requested_model | deepseek/deepseek-v4-pro-0813 |
| served_models | deepseek/deepseek-v4-pro-0813 |
| served_models_distinct | 1 |
| served_model_changed | false |
| providers | NextBit |
| providers_distinct | 1 |
| provider_changed | false |
| system_fingerprints | - |
| system_fingerprints_distinct | 0 |
| reasoning_tokens_total | 0 |
| items_with_reasoning | 0 |
| thinking | honoured |
| thinking_evidence_items | 12 |
| seed_requested | 17 |
| seed | uncontrolled |
| temperature | 0.0 |
| max_output_tokens | 2048 |
| json_mode | true |
| provider_order | nextbit |
| allow_fallbacks | false |
| timeout_seconds | 120.0 |

## Spend

Price-derived USD: 0.0277. Provider reported USD: 0.0277. Charged upper bound: 0.0277.

## Notes

Not measured: C2-C1 (condition_not_run); C4-C2 (condition_not_run); C4-C3 (condition_not_run); false_ready (no_non_ready_gold); repair_at_1 (not_run); slot_match (no_non_ready_gold)

Files: summary.json, outcomes.jsonl, receipts/.
