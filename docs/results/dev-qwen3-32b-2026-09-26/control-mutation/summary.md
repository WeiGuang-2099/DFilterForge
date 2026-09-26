# Score summary

Model: control-mutation. Split: dev. Run: dev-qwen3-32b-2026-09-26. Cases: 20, items: 80.
Gold hash: 6597c4d22cb9. Bootstrap: 1,000 case-level resamples, seed 17, nearest-rank 2.5 and 97.5 percentiles, index vectors shared by every ready-gold metric, drawn from 12 ready cases.

## Conditions

| Condition | Items | Compile valid | Strong exact | Silent-wrong (all) | Silent-wrong (exec) | Over-abstention | Shortcut | Provider failed | Malformed | Gold-field recall | Cost USD/item | Latency p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 40 | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] | 1.000 (24/24) [1.000, 1.000] | 0.000 [0.000, 0.000] | 0 | 0 | 0 | n/a | n/a | 0 |
| C2 | 40 | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] | 1.000 (24/24) [1.000, 1.000] | 0.000 [0.000, 0.000] | 0 | 0 | 0 | 0.639 full 0.458 at k<=16 | n/a | 0 |

Compile valid means C1 and C2 were accepted and run by pinned tshark only, so an accepted name outside the frozen catalog still counts as valid; C3 and C4 additionally bind the frozen catalog and check types, operators and values.
Items, Shortcut, Provider failed and Malformed count non-ready items too; every rate in this table covers ready gold only.
Intervals drawn from fewer than 1,000 resamples skip draws whose denominator is zero: C1 slot match 998; C2 slot match 998.
## Non-ready gold

| Condition | False-ready | Clarification | Not expressible | Slot match |
| --- | ---: | ---: | ---: | ---: |
| C1 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] |
| C2 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] |

Rates above this table cover ready gold only; these cover the 8 non-ready cases, resampled with their own index vectors.


## Comparisons

| Comparison | Metric | Difference | First better | Second better | Discordant | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| C2 - C1 | strong exact | 0.000 [0.000, 0.000] | 0 | 0 | 0 | inconclusive (fewer than 10 discordant cases) |

## Notes

Not measured: C3 (no_typed_mutation); C4 (no_typed_mutation); C4-C2 (condition_not_run); C4-C3 (condition_not_run); repair_at_1 (not_run)

Files: summary.json, outcomes.jsonl, receipts/.
