# Case expansion: 52 ready and 24 non-ready cases

## Problem

The split held 8 dev and 16 test ready cases and no non-ready ones. The eight dev cases gave
comparison intervals about half a unit wide, and sixteen test cases would give only about 4 to
6 discordant cases at the discordance rates below, under the 10 the protocol requires, so most
comparisons could only come out inconclusive. The scorer could grade needs_clarification and
not_expressible gold, but with no such case false-ready rate and slot match were unmeasurable.

## Size

A power simulation run before any case was written put the targets in `docs/protocol.md` to
the test; its script was not committed, so these figures cannot be rechecked from the
repository. With the correlation between a case's two requests fitted on the first dev runs
(0.55), it gave a C4 - C2 interval 0.19 wide at 40 test cases with 2 requests each when a
quarter of the cases are discordant, and 0.25 when three eighths are. One request per case
widened it by 19 to 29 percent, and 48 cases narrowed it by about 8 percent. So the targets
stand: 12 ready, 4 needs_clarification and 4 not_expressible on dev; 40, 8 and 8 on test.

## Cases

- Ready: 48 candidates were drafted (the drafting notes were not committed), with labels
  written by hand from the recipe and witness tables, never from a filter. 41 passed the
  adequacy gate on the current witness packets; 7 would need a new witness and were dropped
  rather than move the dev probes. Of the 41, six pairs differed by one packet type, so one of
  each was dropped, and two left the gate little to test. From the remaining candidates, 28
  were chosen: 4 dev, 24 test. Five use TEST-NET-1 in a way the dev clients cannot separate,
  so they are test cases.
- Non-ready: 8 dev and 16 test, half of each status. A clarification case leaves one thing
  open (an address, port, value, direction, field or protocol) and names it as gold; the
  which-TCP-flag case accepts field or value. Dev uses the address, port, value and direction
  slots; test adds field and protocol. A not-expressible case asks for an order, a ranking, a
  statistic or relation across packets, an edit or enforcement action, or a fact the capture
  does not hold. Three rationales are marked contestable: the OS default TTL, the port scan
  and the lost packets, where a model could defend a filter.
- Requests: every new case, and the 16 old test cases, got two requests written from a card of
  the gold in plain language. The two requests of a case were drafted separately; the second
  was the one of three candidates sharing the fewest content words with the first. Independent
  checks read each pair against the gold, and the owner reviewed all 68 pairs. The pre-freeze
  review below then changed five requests in four cases, written directly rather than by the
  candidate procedure, and the owner approved those too. The 16 old dev requests are
  unchanged, so the published runs still answer the same text.
- Numbering: each split and gold kind numbers its items from its own block: dev ready from
  mei-0001, dev non-ready from 0501, test ready from 1001, test non-ready from 1501. A case
  added to one block moves no other item, so the frozen test IDs cannot move with dev.

## Review before the freeze

Six independent review agents read the commits for weakened tests, code, stale text and the
meaning of every new request. They found no request that disagrees with its ready gold. They
did find a test request 71 retrieval tokens long, over the 64 the retriever accepts, which
would have stopped every test prepare; a request whose "64 - 1" could read as 63; a direction
case on mDNS's port 5353, where direction by port does not split traffic; the lost-packets
case not marked contestable; a which-TCP-flag case that accepted only the field slot; and test
numbers that would have moved with dev. All were fixed before the freeze, and a test now runs
every request of both splits through the real retriever. Following the same review, tests
check that the committed non-ready gold scores as matched (false-ready 0, slot match 1) end to
end and under the reference control, that the mutation control is false-ready on all 16 dev
non-ready items, and that no non-ready case id or rationale reaches a prompt.

## Gate evidence

[Before](evidence/dns-fin-gate-after.json), strict mode at a1d3724: 24 cases, 192 mutants, 0
survivors without a waiver, 4 equivalent waivers. The refactor fbe2ae7 regenerates the same
inputs, gold and captures byte for byte.

[After](evidence/case-expansion-gate.json), strict mode at bb39ab7, the commit that added
the ready cases: 52 cases, 344 mutants (72 dev, 272 test), 0 survivors without a waiver, the
same 4 waivers, and 0 label, canonical or mutation-label mismatches on all six probes. Later
commits add the non-ready cases and change request text, item numbering, non-ready slots and
comments; none changes a ready filter, typed target, label or capture, and the gate run in CI
at bb037b8 gives the same counts. The receipt's gold and source-file hashes describe bb39ab7.
A CI test fails on any request containing a dotted field name from the frozen catalog, such as
tcp.dstport, or one of the operators ==, !=, <=, >=, &&, || or in {...}; all 152 requests pass.

## Effect on published numbers

None. Dev items mei-0001 to mei-0016 keep their text and IDs, every committed prompt still
matches the regenerated split, and `score --check` reproduces all six committed outputs. A
new dev pass is 40 items per condition (24 ready and 16 non-ready), 160 requests over the four
conditions.

## Limits

- Test holds 112 items, above the 64 a prepare manifest accepts; the bounds are raised in the
  freeze slice, before any test item is sent.
- The three contestable cases are kept and scored as written; the port-scan and lost-packets
  rationales say why, and the OS-default-TTL rationale only marks the case contestable.
- The address, port, value and direction slots and most kinds of inexpressible request repeat
  across splits by design (the field and protocol slots and the cross-packet statistics are
  test-only, the ranking dev-only), so prompt choices made on dev may carry over to test
  non-ready scores more than to ready ones.
- A near miss the gate's single-site operators do not generate is still untested, as before.

## Decision

Keep all 76 cases. Freeze the test split next: raise the prepare bounds, then record its input
hashes in `docs/protocol.md` before any test item is sent.
