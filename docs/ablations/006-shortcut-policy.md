# Ablation 006: Shortcut Policy

Status: keep_full

Measured: 2026-09-24

## Hypothesis

A filter can match every labelled frame and still say nothing about the request:
it can count frames, read the capture clock, follow a stream index, or copy a
constant the generator happened to use. Scoring such an answer as strong exact
would reward exactly what repair feedback and preference training could teach a
model to exploit. The protocol now scores it `shortcut`. The question for the
ablation is whether the policy needs the frozen catalog's field types, or whether
name rules alone would do.

## Frozen inputs

- Full revision: `b281d24+working-tree`; receipt
  [evidence/006-shortcut-policy.json](evidence/006-shortcut-policy.json), sha256
  `8f25304ac26e6dfea9fcc35c46f3d650187ac3ffb9a1454436815b1fdf4091a4`.
- Simplified: the same `dfilterforge.shortcuts` rules given no catalog types
  (`find_shortcuts(found, request, {})`), measured in the same receipt.
- tshark 4.6.8 in the Docker test image; the frozen catalog, sha256
  `8be7163808fe356cb253ff6fd2006d7651297b62b1b6392d0c5d8428f65523f4`.
- Dataset: the 24 model split cases on their six probes; eight shortcut filters
  listed in `scripts/shortcut_ablation.py`, written before any of them was run;
  the 24 reference filters, authored mutations and canonical IRs plus 192
  single-site mutants; the 84 executed answers of the two committed dev runs.
- Quality threshold: 0 flagged gold candidates and 0 flagged committed answers;
  a probe-exact shortcut must never score strong exact.
- Performance threshold: the policy's cost per answer stays negligible beside
  one tshark call (about 60 ms).

## Full

`dfilterforge.shortcuts` reads field names and literals from the typed IR, or
from a lexical scan of a display filter that sets quoted strings aside. It flags
a field the catalog types `FT_FRAMENUM`, `FT_ABSOLUTE_TIME` or
`FT_RELATIVE_TIME`, a `frame.` field other than len, cap_len and protocols, a
`_ws.` field or a stream index; ip.id, dns.id, a checksum or a raw sequence
number; and a literal the request does not state: a single host address, a
network touching 198.51.100.0/24, a number of 41000 or more, a MAC address or a
generated DNS name. `catalog_runtime.tshark_types` reads the types from the
frozen inventory, read-only. Scoring records the hits and the OR count on every
executed answer, and a probe-exact answer with a hit is `shortcut`.

## Simplified

The same module with an empty type map: the name rules and the constant rules
stay, the catalog lookup goes.

## Commands

```text
docker run --rm --network none --tmpfs /tmp:rw,exec,size=512m \
  -v "$PWD/src:/workspace/src:ro" -v "$PWD/scripts:/workspace/scripts:ro" \
  -v "$PWD/pyproject.toml:/workspace/pyproject.toml:ro" \
  -v "$PWD/docs/results:/workspace/results:ro" -v "$PWD/out:/out" \
  dfilterforge-test:0.1.0 python scripts/shortcut_ablation.py \
  --output /out/006-shortcut-policy.json --results-dir /workspace/results \
  --source-revision b281d24+working-tree
```

## Results

| Measure | Full | Simplified | Delta |
| --- | ---: | ---: | ---: |
| Catalog frame-number and time fields caught | 2,470 / 2,470 | 13 / 2,470 | +2,457 |
| Shortcut filters exact on their probes | 6 / 8 | 6 / 8 | 0 |
| Of those, scored strong exact | 0 | 3 | -3 |
| Gold candidates flagged | 0 / 264 | 0 / 264 | 0 |
| Committed answers flagged | 0 / 84 | 0 / 84 | 0 |
| Median check per committed answer (ms) | 0.095 | 0.013 | +0.082 |
| Production lines | 374 | at most 326 | at least +48 |

Full's 374 lines are shortcuts.py (326) and `tshark_types` (48); Simplified
keeps shortcuts.py less its type rule.

The three filters Simplified passes as strong exact each add one conjunct the
name rules cannot read: `!dns.response_in` on udp-expiring-ttl,
`!(tcp.time_delta > 100)` on tcp-expiring-ttl and `!dns.response_to` on
dns-a-queries. Each is true on every probe packet of its case. The first two
would drop the right packet in another capture: a low-TTL query whose answer
was also captured, or a TCP segment more than 100 s after the one before it
once conversation timestamps are on. The third never changes a query's
meaning, since only responses carry it; it is flagged because the rule judges
what a filter mentions, not what the mention does on these probes. The name
rules miss 32 such fields in the recipe world's own protocols alone
(dns.response_in, dns.time, tcp.analysis.acks_frame, tcp.time_relative,
ip.reassembled_in and others). The two filters that were not exact replace the intent with the server
pool and the ephemeral port range; the witness tail already makes both
silent-wrong, and both variants record the hit.

No committed answer breaks a rule, so the re-score of both dev runs and their
controls changes no outcome: 25 and 35 strong exact, controls 64/64 and 32/32.
Every executed answer has at most one OR.

## Decision

`keep_full`. Without catalog types the policy is not behaviourally equivalent:
it scores three probe-exact shortcuts as strong exact, and every one of them is a
field any model could name. The catalog lookup costs about a tenth of a
millisecond per answer against about 60 ms per tshark call.

Limits: the scan finds names and literals, not meaning, so a shortcut spelled
only with ordinary fields (a subnet that happens to hold every server) is left
to the probes. The over-wide disjunction rule is measured, not judged, until
repair or training answers show one. A request that states a constant makes it
allowed, so the rule is only as strict as the requests are specific.
