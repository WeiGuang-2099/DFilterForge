# Error-class hand check, 2026-10-19

`docs/protocol.md` (Training rules, amended 2026-10-18) registers the
error classes of the self-served rows on test C4 and asks for ten items,
drawn by `random.Random(17).sample` from every classified item of the four
rows listed by row and item id, to be checked by hand. The classes were
defined after seed 2026's test scores were known; they describe answers
and decide nothing.

`scripts/sft_analysis.py` draws the sample into
[analysis.json](analysis.json) (`classes.check`): ten of the 220 ready C4
items of the base row and the three seeds that are not strong exact. The
maintainer read each item's committed request, reference filter, scored
outcome and stored answer (the receipt, the stored IR or the raw reply)
and asked one question: does the class the registered order gives match
what the files show?

| # | Row | Item | Case | Class | Agrees | What the files show |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | seed 42 | mei-1008 | source-testnet-or-private | `extra_field` | yes | The answer joins the two ranges with AND and tests `ip.dst` for the second, a field the gold does not test. |
| 2 | seed 17 | mei-1043 | syn-without-ece | `abstained` | yes | It asks which direction is meant, on a request that says no direction restriction applies. |
| 3 | seed 2026 | mei-1059 | dns-query-off-port-53 | `missing_field` | yes | The answer drops `dns.flags.response`, so responses pass. Its `udp && !(udp.dstport == 53)` selects what the gold's `udp.dstport != 53` does, since tshark's `!=` is false where the field is absent. |
| 4 | seed 17 | mei-1003 | udp-source-testnet | `unknown_field` | yes | The frozen catalog has no `udp.srcip`, so the answer is invalid with `unknown_field`. It would also require `dns`, though the request keeps plain UDP. |
| 5 | seed 17 | mei-1024 | aaaa-or-udp-source-dns | `extra_field` | yes | The answer ORs in `udp`, `dns` and `udp.dstport`, and asks for query type 2 where the gold asks for 28. |
| 6 | base | mei-1080 | https-from-outside-testnet | `invalid_other` | yes | Invalid with `type_mismatch`: it compares `msdp.not.source_address`, an IPv4 field, with the string `"0"`. It also tests `ip.addr` where the gold negates `ip.src`, and adds `tcp.srcport == 0`. |
| 7 | base | mei-1049 | ack-without-syn | `extra_field` | yes | The answer adds four flag and completeness fields and requires SYN set where the gold requires it clear. |
| 8 | seed 2026 | mei-1036 | tcp-without-port-443 | `missing_field` | yes | It tests `tcp.srcport` and `tcp.dstport` for `tcp.port`, and requires `udp` in place of `tcp` where the request says no UDP. |
| 9 | seed 2026 | mei-1005 | private-either-endpoint | `missing_field` | yes | It tests `ip.addr` for `ip.src` or `ip.dst`, then ORs in `tcp`, `udp`, `dns` and two port fields, which match every frame of all three probes. |
| 10 | seed 42 | mei-1018 | low-port-dns-a | `extra_field` | yes | It adds `dns.flags.response == false`, dropping the responses the request keeps. |

All ten classes match the registered rule. Seven of them, items 1 and 4
to 9, name one difference of an answer that differs from the reference in
more ways: a wrong join, a wrong value or polarity, a field in place of
another, or an extra term. Items 2, 3 and 10 show nothing beyond what their
class names.
In item 9 the missing fields are spelled another way, `ip.addr` for
`ip.src` or `ip.dst`, which alone would select the same packets; in item 8
the two port fields stand for `tcp.port` the same way, while `tcp` itself
is replaced by `udp`. A class names the first registered difference, not
the cause of the failure, and the pages that show the classes say so.
