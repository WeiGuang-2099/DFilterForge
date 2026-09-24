# Score summary

Model: qwen/qwen3-32b. Split: dev. Run: dev-qwen3-32b-2026-09-21. Cases: 8, items: 64.
Gold hash: 8a061589fe6c. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every metric, drawn from 8 cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 16 | 0.750 [0.562, 0.938] | 0.500 [0.188, 0.750] | 0.250 [0.062, 0.500] | 0.333 (4/12) [0.071, 0.727] | 0.062 [0.000, 0.188] | 0 | 0 | 0 | n/a | 0.000051 | 4438 |
| C2 | 16 | 0.812 [0.562, 1.000] | 0.562 [0.250, 0.875] | 0.250 [0.062, 0.500] | 0.308 (4/13) [0.062, 0.636] | 0.125 [0.000, 0.375] | 0 | 0 | 0 | 0.740 full 0.625 at k<=16 | 0.000101 | 4093 |
| C3 | 16 | 0.062 [0.000, 0.188] | 0.062 [0.000, 0.188] | 0.000 [0.000, 0.000] | 0.000 (0/1) [0.000, 0.000] | 0.000 [0.000, 0.000] | 0 | 0 | 0 | n/a | 0.000084 | 6765 |
| C4 | 16 | 0.562 [0.375, 0.750] | 0.438 [0.188, 0.688] | 0.125 [0.000, 0.312] | 0.222 (2/9) [0.000, 0.625] | 0.062 [0.000, 0.188] | 0 | 0 | 1 | 0.740 full 0.625 at k<=16 | 0.000133 | 6421 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Intervals drawn from fewer than 1,000 resamples skip draws whose denominator is zero: C3 silent-wrong (exec) 647.

## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C4 - C2 | strong exact | -0.125 [-0.375, 0.125] | 1 | 3 | 4 | inconclusive (fewer than 10 discordant cases) |
| C2 - C1 | strong exact | 0.062 [-0.375, 0.500] | 4 | 2 | 6 | inconclusive (fewer than 10 discordant cases) |
| C4 - C3 | strong exact | 0.375 [0.125, 0.688] | 4 | 0 | 4 | inconclusive (fewer than 10 discordant cases) |

With 8 cases no comparison can reach 10 discordant cases, so every verdict is inconclusive by construction.

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
| thinking_evidence_items | 64 |
| seed_requested | 17 |
| seed | uncontrolled |
| temperature | 0.0 |
| max_output_tokens | 2048 |
| json_mode | true |
| provider_order | deepinfra |
| allow_fallbacks | false |
| timeout_seconds | 120.0 |

## Spend

Price-derived USD: 0.0059. Provider reported USD: 0.0059. Charged upper bound: 0.0059.

## Notes

Not measured: false_ready (no_non_ready_gold); repair_at_1 (not_run); slot_match (no_non_ready_gold)

Files: summary.json, outcomes.jsonl, receipts/.
