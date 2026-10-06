# Score summary

Model: qwen/qwen3.5-122b-a10b. Split: test. Run: test-qwen3.5-122b-a10b-cx-2026-09-26. Cases: 16, items: 20.
Gold hash: 804ae34c2a19. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every metric, drawn from 16 cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C4 | 20 | 0.719 [0.500, 0.906] | 0.469 [0.250, 0.719] | 0.250 [0.062, 0.438] | 0.348 (5/14) [0.105, 0.609] | 0.062 [0.000, 0.188] | 0 | 0 | 1 | 0.609 full 0.281 at k<=16 | 0.001836 | 2282 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.

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
| thinking_evidence_items | 20 |
| seed_requested | 17 |
| seed | uncontrolled |
| temperature | 0.0 |
| max_output_tokens | 2048 |
| json_mode | true |
| provider_order | novita |
| allow_fallbacks | false |
| timeout_seconds | 120.0 |

## Spend

Price-derived USD: 0.0367. Provider reported USD: 0.0367. Charged upper bound: 0.0367.

## Notes

Not measured: C2-C1 (condition_not_run); C4-C2 (condition_not_run); C4-C3 (condition_not_run); false_ready (no_non_ready_gold); repair_at_1 (not_run); slot_match (no_non_ready_gold)

Files: summary.json, outcomes.jsonl, receipts/.
