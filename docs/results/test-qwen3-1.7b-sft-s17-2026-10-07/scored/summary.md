# Score summary

Model: qwen3-1.7b-sft-s17. Split: test. Run: test-qwen3-1.7b-sft-s17-2026-10-07. Cases: 56, items: 448.
Gold hash: a9632daadafe. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every ready-gold metric, drawn from 40 ready cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 112 | 0.487 [0.350, 0.625] | 0.250 [0.138, 0.362] | 0.237 [0.125, 0.350] | 0.487 (19/39) [0.298, 0.675] | 0.263 [0.163, 0.375] | 0 | 0 | 2 | n/a | 0.000004 | 1687 |
| C2 | 112 | 0.500 [0.375, 0.625] | 0.212 [0.113, 0.325] | 0.287 [0.175, 0.412] | 0.575 (23/40) [0.381, 0.756] | 0.212 [0.125, 0.300] | 0 | 0 | 3 | 0.592 full 0.350 at k<=16 | 0.000011 | 1750 |
| C3 | 112 | 0.613 [0.500, 0.725] | 0.263 [0.163, 0.362] | 0.350 [0.237, 0.463] | 0.571 (28/49) [0.415, 0.712] | 0.138 [0.050, 0.237] | 0 | 0 | 6 | n/a | 0.000007 | 2594 |
| C4 | 112 | 0.738 [0.637, 0.825] | 0.338 [0.237, 0.450] | 0.400 [0.287, 0.512] | 0.542 (32/59) [0.404, 0.672] | 0.075 [0.025, 0.138] | 0 | 0 | 3 | 0.592 full 0.350 at k<=16 | 0.000014 | 2593 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Items, Shortcut, Provider failed and Malformed count non-ready items too; every rate in this table covers ready gold only.
## Non-ready gold

| Condition | False-ready | Clarification | Not expressible | Slot match |
| --- | ---: | ---: | ---: | ---: |
| C1 | 0.156 [0.000, 0.344] | 0.062 [0.000, 0.214] | 0.250 [0.000, 0.571] | 0.250 [0.000, 0.556] |
| C2 | 0.156 [0.000, 0.344] | 0.062 [0.000, 0.200] | 0.250 [0.000, 0.571] | 0.438 [0.250, 0.667] |
| C3 | 0.188 [0.000, 0.375] | 0.000 [0.000, 0.000] | 0.375 [0.000, 0.714] | 0.750 [0.500, 1.000] |
| C4 | 0.250 [0.062, 0.500] | 0.125 [0.000, 0.400] | 0.375 [0.000, 0.714] | 0.812 [0.562, 1.000] |

Rates above this table cover ready gold only; these cover the 16 non-ready cases, resampled with their own index vectors.


## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C4 - C2 | strong exact | 0.125 [0.025, 0.225] | 11 | 3 | 14 | conclusive |
| C2 - C1 | strong exact | -0.037 [-0.100, 0.025] | 2 | 5 | 7 | inconclusive (fewer than 10 discordant cases) |
| C4 - C3 | strong exact | 0.075 [-0.013, 0.163] | 9 | 3 | 12 | conclusive |

## Run settings

| Setting | Value |
| --- | --- |
| requested_model | qwen3-1.7b-sft-s17 |
| served_models | qwen3-1.7b-sft-s17 |
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

Price-derived USD: 0.0039. Provider reported USD: n/a. Charged upper bound: 0.0042.
Price-derived cost is a lower bound: 156 items spent tokens on a retry.

## Notes

Not measured: repair_at_1 (not_run)

Files: summary.json, outcomes.jsonl, receipts/.
