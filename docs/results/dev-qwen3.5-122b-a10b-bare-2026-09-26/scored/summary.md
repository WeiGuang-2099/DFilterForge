# Score summary

Model: qwen/qwen3.5-122b-a10b. Split: dev. Run: dev-qwen3.5-122b-a10b-bare-2026-09-26. Cases: 7, items: 8.
Gold hash: 950424b675b9. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every metric, drawn from 7 cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C4 | 8 | 0.571 [0.143, 0.857] | 0.286 [0.000, 0.571] | 0.286 [0.000, 0.714] | 0.500 (2/4) [0.000, 1.000] | 0.000 [0.000, 0.000] | 0 | 0 | 1 | 0.643 full 0.429 at k<=16 | 0.001508 | 2937 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Intervals drawn from fewer than 1,000 resamples skip draws whose denominator is zero: C4 silent-wrong (exec) 995.

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
| thinking_evidence_items | 8 |
| seed_requested | 17 |
| seed | uncontrolled |
| temperature | 0.0 |
| max_output_tokens | 2048 |
| json_mode | true |
| provider_order | novita |
| allow_fallbacks | false |
| timeout_seconds | 120.0 |

## Spend

Price-derived USD: 0.0121. Provider reported USD: 0.0121. Charged upper bound: 0.0121.

## Notes

Not measured: C2-C1 (condition_not_run); C4-C2 (condition_not_run); C4-C3 (condition_not_run); false_ready (no_non_ready_gold); repair_at_1 (not_run); slot_match (no_non_ready_gold)

Files: summary.json, outcomes.jsonl, receipts/.
