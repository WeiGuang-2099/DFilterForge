# Score summary

Model: Qwen/Qwen3-1.7B. Split: dev. Run: dev-qwen3-1.7b-2026-10-07. Cases: 20, items: 160.
Gold hash: 6597c4d22cb9. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every ready-gold metric, drawn from 12 ready cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 40 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | n/a (0/0) | 0.250 [0.083, 0.417] | 0 | 0 | 15 | n/a | 0.000005 | 2469 |
| C2 | 40 | 0.417 [0.167, 0.625] | 0.000 [0.000, 0.000] | 0.417 [0.167, 0.625] | 1.000 (10/10) [1.000, 1.000] | 0.000 [0.000, 0.000] | 0 | 0 | 4 | 0.639 full 0.458 at k<=16 | 0.000013 | 2437 |
| C3 | 40 | 0.042 [0.000, 0.125] | 0.000 [0.000, 0.000] | 0.042 [0.000, 0.125] | 1.000 (1/1) [1.000, 1.000] | 0.000 [0.000, 0.000] | 0 | 0 | 16 | n/a | 0.000008 | 3656 |
| C4 | 40 | 0.292 [0.083, 0.542] | 0.000 [0.000, 0.000] | 0.292 [0.083, 0.542] | 1.000 (7/7) [1.000, 1.000] | 0.000 [0.000, 0.000] | 0 | 0 | 12 | 0.639 full 0.458 at k<=16 | 0.000016 | 4344 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Items, Shortcut, Provider failed and Malformed count non-ready items too; every rate in this table covers ready gold only.
Intervals drawn from fewer than 1,000 resamples skip draws whose denominator is zero: C1 slot match 998; C2 slot match 998; C3 silent-wrong (exec) 631; C3 slot match 998; C4 silent-wrong (exec) 998; C4 slot match 998.
## Non-ready gold

| Condition | False-ready | Clarification | Not expressible | Slot match |
| --- | ---: | ---: | ---: | ---: |
| C1 | 0.375 [0.125, 0.688] | 0.375 [0.000, 0.900] | 0.375 [0.000, 0.833] | 0.125 [0.000, 0.375] |
| C2 | 0.812 [0.625, 0.938] | 0.875 [0.500, 1.000] | 0.750 [0.500, 1.000] | 0.125 [0.000, 0.500] |
| C3 | 0.438 [0.188, 0.750] | 0.375 [0.000, 0.900] | 0.500 [0.125, 0.900] | 0.000 [0.000, 0.000] |
| C4 | 0.562 [0.375, 0.750] | 0.500 [0.100, 0.833] | 0.625 [0.500, 0.900] | 0.000 [0.000, 0.000] |

Rates above this table cover ready gold only; these cover the 8 non-ready cases, resampled with their own index vectors.


## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C4 - C2 | strong exact | 0.000 [0.000, 0.000] | 0 | 0 | 0 | inconclusive (fewer than 10 discordant cases) |
| C2 - C1 | strong exact | 0.000 [0.000, 0.000] | 0 | 0 | 0 | inconclusive (fewer than 10 discordant cases) |
| C4 - C3 | strong exact | 0.000 [0.000, 0.000] | 0 | 0 | 0 | inconclusive (fewer than 10 discordant cases) |

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
| thinking_evidence_items | 160 |
| seed_requested | 17 |
| seed | uncontrolled |
| temperature | 0.0 |
| max_output_tokens | 2048 |
| json_mode | true |
| provider_order | - |
| allow_fallbacks | n/a |
| timeout_seconds | 120.0 |

## Spend

Price-derived USD: 0.0017. Provider reported USD: n/a. Charged upper bound: 0.0018.

## Notes

Not measured: repair_at_1 (not_run)

Files: summary.json, outcomes.jsonl, receipts/.
