# Score summary

Model: Qwen/Qwen3-1.7B. Split: test. Run: test-qwen3-1.7b-2026-10-07. Cases: 56, items: 448.
Gold hash: a9632daadafe. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every ready-gold metric, drawn from 40 ready cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 112 | 0.125 [0.062, 0.212] | 0.050 [0.013, 0.100] | 0.075 [0.025, 0.138] | 0.600 (6/10) [0.286, 0.875] | 0.312 [0.225, 0.412] | 0 | 0 | 39 | n/a | 0.000005 | 2625 |
| C2 | 112 | 0.338 [0.225, 0.463] | 0.163 [0.075, 0.275] | 0.175 [0.087, 0.263] | 0.519 (14/27) [0.294, 0.742] | 0.025 [0.000, 0.062] | 0 | 0 | 12 | 0.592 full 0.350 at k<=16 | 0.000013 | 2578 |
| C3 | 112 | 0.037 [0.000, 0.100] | 0.000 [0.000, 0.000] | 0.037 [0.000, 0.100] | 1.000 (3/3) [1.000, 1.000] | 0.000 [0.000, 0.000] | 0 | 0 | 34 | n/a | 0.000008 | 4063 |
| C4 | 112 | 0.388 [0.263, 0.512] | 0.062 [0.025, 0.113] | 0.325 [0.212, 0.438] | 0.839 (26/31) [0.720, 0.943] | 0.000 [0.000, 0.000] | 0 | 0 | 29 | 0.592 full 0.350 at k<=16 | 0.000016 | 4547 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Items, Shortcut, Provider failed and Malformed count non-ready items too; every rate in this table covers ready gold only.
Intervals drawn from fewer than 1,000 resamples skip draws whose denominator is zero: C3 silent-wrong (exec) 863.
## Non-ready gold

| Condition | False-ready | Clarification | Not expressible | Slot match |
| --- | ---: | ---: | ---: | ---: |
| C1 | 0.094 [0.000, 0.250] | 0.000 [0.000, 0.000] | 0.188 [0.000, 0.500] | 0.312 [0.071, 0.571] |
| C2 | 0.750 [0.625, 0.875] | 0.750 [0.571, 0.929] | 0.750 [0.562, 0.929] | 0.188 [0.000, 0.357] |
| C3 | 0.531 [0.375, 0.688] | 0.625 [0.357, 0.833] | 0.438 [0.214, 0.643] | 0.062 [0.000, 0.200] |
| C4 | 0.750 [0.594, 0.906] | 0.750 [0.444, 1.000] | 0.750 [0.571, 0.938] | 0.000 [0.000, 0.000] |

Rates above this table cover ready gold only; these cover the 16 non-ready cases, resampled with their own index vectors.


## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C4 - C2 | strong exact | -0.100 [-0.212, 0.000] | 3 | 7 | 10 | conclusive |
| C2 - C1 | strong exact | 0.113 [0.000, 0.225] | 8 | 3 | 11 | conclusive |
| C4 - C3 | strong exact | 0.062 [0.025, 0.113] | 5 | 0 | 5 | inconclusive (fewer than 10 discordant cases) |

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

Price-derived USD: 0.0047. Provider reported USD: n/a. Charged upper bound: 0.0050.

## Notes

Not measured: repair_at_1 (not_run)

Files: summary.json, outcomes.jsonl, receipts/.
