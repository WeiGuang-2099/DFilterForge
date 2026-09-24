# Score summary

Model: control-reference. Split: dev. Run: dev-qwen3-32b-2026-09-21. Cases: 8, items: 64.
Gold hash: 8a061589fe6c. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every metric, drawn from 8 cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 16 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 0.000 (0/16) [0.000, 0.000] | 0.000 [0.000, 0.000] | 0 | 0 | 0 | n/a | n/a | 0 |
| C2 | 16 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 0.000 (0/16) [0.000, 0.000] | 0.000 [0.000, 0.000] | 0 | 0 | 0 | 0.740 full 0.625 at k<=16 | n/a | 0 |
| C3 | 16 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 0.000 (0/16) [0.000, 0.000] | 0.000 [0.000, 0.000] | 0 | 0 | 0 | n/a | n/a | 0 |
| C4 | 16 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 0.000 (0/16) [0.000, 0.000] | 0.000 [0.000, 0.000] | 0 | 0 | 0 | 0.740 full 0.625 at k<=16 | n/a | 0 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.

## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C4 - C2 | strong exact | 0.000 [0.000, 0.000] | 0 | 0 | 0 | inconclusive (fewer than 10 discordant cases) |
| C2 - C1 | strong exact | 0.000 [0.000, 0.000] | 0 | 0 | 0 | inconclusive (fewer than 10 discordant cases) |
| C4 - C3 | strong exact | 0.000 [0.000, 0.000] | 0 | 0 | 0 | inconclusive (fewer than 10 discordant cases) |

With 8 cases no comparison can reach 10 discordant cases, so every verdict is inconclusive by construction.

## Notes

Not measured: false_ready (no_non_ready_gold); repair_at_1 (not_run); slot_match (no_non_ready_gold)

Files: summary.json, outcomes.jsonl, receipts/.
