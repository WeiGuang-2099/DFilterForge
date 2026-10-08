# Score summary

Model: qwen3-1.7b-sft-s2026. Split: dev. Run: dev-qwen3-1.7b-sft-s2026-2026-10-07. Cases: 20, items: 160.
Gold hash: 6597c4d22cb9. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every ready-gold metric, drawn from 12 ready cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 40 | 0.375 [0.167, 0.583] | 0.042 [0.000, 0.125] | 0.292 [0.125, 0.500] | 0.778 (7/9) [0.500, 1.000] | 0.208 [0.083, 0.375] | 1 | 0 | 0 | n/a | 0.000003 | 1828 |
| C2 | 40 | 0.458 [0.250, 0.667] | 0.083 [0.000, 0.208] | 0.375 [0.208, 0.542] | 0.818 (9/11) [0.636, 1.000] | 0.250 [0.083, 0.458] | 0 | 0 | 2 | 0.639 full 0.458 at k<=16 | 0.000010 | 1875 |
| C3 | 40 | 0.792 [0.542, 1.000] | 0.250 [0.083, 0.417] | 0.542 [0.292, 0.750] | 0.684 (13/19) [0.444, 0.900] | 0.042 [0.000, 0.125] | 0 | 0 | 2 | n/a | 0.000006 | 2484 |
| C4 | 40 | 0.667 [0.417, 0.875] | 0.250 [0.083, 0.417] | 0.417 [0.208, 0.625] | 0.625 (10/16) [0.375, 0.867] | 0.083 [0.000, 0.208] | 0 | 0 | 4 | 0.639 full 0.458 at k<=16 | 0.000013 | 2500 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Items, Shortcut, Provider failed and Malformed count non-ready items too; every rate in this table covers ready gold only.
Intervals drawn from fewer than 1,000 resamples skip draws whose denominator is zero: C1 slot match 998; C2 slot match 998; C3 slot match 998; C4 slot match 998.
## Non-ready gold

| Condition | False-ready | Clarification | Not expressible | Slot match |
| --- | ---: | ---: | ---: | ---: |
| C1 | 0.312 [0.062, 0.625] | 0.125 [0.000, 0.375] | 0.500 [0.000, 1.000] | 0.875 [0.625, 1.000] |
| C2 | 0.188 [0.000, 0.438] | 0.000 [0.000, 0.000] | 0.375 [0.000, 0.875] | 1.000 [1.000, 1.000] |
| C3 | 0.500 [0.188, 0.812] | 0.500 [0.000, 1.000] | 0.500 [0.125, 0.875] | 0.500 [0.000, 1.000] |
| C4 | 0.312 [0.125, 0.562] | 0.125 [0.000, 0.500] | 0.500 [0.125, 0.875] | 0.875 [0.500, 1.000] |

Rates above this table cover ready gold only; these cover the 8 non-ready cases, resampled with their own index vectors.


## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C4 - C2 | strong exact | 0.167 [0.042, 0.292] | 4 | 0 | 4 | inconclusive (fewer than 10 discordant cases) |
| C2 - C1 | strong exact | 0.042 [0.000, 0.125] | 1 | 0 | 1 | inconclusive (fewer than 10 discordant cases) |
| C4 - C3 | strong exact | 0.000 [0.000, 0.000] | 0 | 0 | 0 | inconclusive (fewer than 10 discordant cases) |

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

Price-derived USD: 0.0013. Provider reported USD: n/a. Charged upper bound: 0.0014.

## Notes

Not measured: repair_at_1 (not_run)

Files: summary.json, outcomes.jsonl, receipts/.
