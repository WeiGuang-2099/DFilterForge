# Ablation 005: Probe Witnesses

Status: keep_full

Measured: 2026-09-23

## Hypothesis

A fixed tail of witness packets on the six model split probes should kill the
single-site near misses the benchmark recipes leave exact, without changing a
label on any benchmark frame, so that strong exact means what the gold says.
The first dev run scored three wrong filters as strong exact for lack of such
packets ([first dev run](../decisions/first-dev-run.md)).

## Frozen inputs

- Full revision: `7bafd27+working-tree`; receipt
  [evidence/005-probe-adequacy-full.json](evidence/005-probe-adequacy-full.json),
  sha256 `2d46e0cd87de75225ca76d17efe2f18d6480d445385e0ddf26cea0ba41b91acb`,
  measurement identity `58527f003c019d99f18d8778a91141c39356b58e513588e679f0548ea4059238`.
- Simplified revision: `c3d4060+working-tree`, every hashed source file equal
  to commit 7bafd27; receipt
  [evidence/005-probe-adequacy-simplified.json](evidence/005-probe-adequacy-simplified.json),
  sha256 `7b2f25a6123015145946c279d8ffeabff8dffa2d75bfd28f1aa5218ddfc3465b`,
  measurement identity `12c57d5ad2a5ff97f981ef4812a3e4dcf12578cc45aa121aa80c3b8f030f196a`.
- Environment hash (both): `8bfb53d31c02b4c36786cd4914840f0808092a7e4fa037058248d4c4ba1bf414`,
  tshark 4.6.8 in the Docker test image.
- Dataset: the 24 model split cases (8 dev, 16 test), their reference filters,
  canonical IRs and authored mutations, on probes semantic-11/17/23 (dev) and
  semantic-31/37/43 (test); 182 single-site mutants from `dfilterforge.mutants`.
- Quality threshold: 0 label mismatches on all six probes, every authored
  mutation distinguished, 0 unwaived survivors, 0 stale waivers.
- Performance threshold: no more than 5 percent regression in tshark p50.

## Full

`dfilterforge.witnesses` builds 31 named packets; `model_split` appends them to
each probe copy after its last benchmark frame, so frames 1..N keep their bytes
(dev 21/22/28 frames become 52/53/59, test 26/27/33 become 57/58/64). Bytes
follow the fixtures conventions and are seed-derived, so dev and test share no
packet. Every case states its witness memberships next to its recipe
memberships, authored from the packet table and the case intent. The gate
`scripts/probe_adequacy.py` checks reference, compiled canonical IR and the
authored mutation against their labels on all six probes, requires the
mutation to differ on its split, runs all 182 mutants, and applies four
reasoned waivers kept beside the gold (`MUTANT_WAIVERS`).

## Simplified

The same cases and mutants on the real state at 7bafd27: probes copied from the
benchmark with no witness tail and no waivers. Its gate (receipt schema 1.0)
did not yet check the authored mutation against its own labels; Full (1.1)
does, which adds 72 tshark runs and changes no survivor count.

## Commands

```text
docker compose --profile dev build test
docker compose --profile pilot build lab
docker compose --profile dev run --rm --volume "${PWD}/artifacts:/workspace/artifacts" test python scripts/probe_adequacy.py --output /workspace/artifacts/005-probe-adequacy-full.json --source-revision 7bafd27+working-tree --report
docker compose --profile dev run --rm test python scripts/probe_adequacy.py --output /tmp/adequacy/receipt.json --source-revision check
docker compose --profile pilot run --rm lab score --run-dir /workspace/results/dev-qwen3-32b-2026-09-21 --code-revision 7bafd27+working-tree
docker compose --profile pilot run --rm lab score --run-dir /workspace/results/dev-qwen3-32b-2026-09-21 --check --code-revision check
```

The Simplified receipt came from the same report command at its revision. The
score commands ran again with `--control reference` and `--control mutation`.
Receipts were written through a bind mount and copied into `evidence/`.

## Results

| Measure | Full | Simplified | Delta |
| --- | ---: | ---: | ---: |
| Mutants executed | 182 | 182 | 0 |
| Survivors (dev / test) | 4 (0 / 4) | 65 (19 / 46) | -61 |
| boundary | 0 / 0 | 6 / 11 | -17 |
| field-swap | 0 / 4 | 2 / 12 | -10 |
| subnet | 0 / 0 | 2 / 12 | -14 |
| value-domain | 0 / 0 | 4 / 4 | -8 |
| flag-as-number | 0 / 0 | 2 / 5 | -7 |
| drop-conjunct | 0 / 0 | 3 / 2 | -5 |
| Waived (equivalent / not_separable) | 4 (4 / 0) | 0 | +4 |
| Unwaived survivors | 0 | 65 | -65 |
| Label checks: reference, canonical | 144/144, 144/144 | 144/144, 144/144 | 0 |
| Label checks: authored mutation | 144/144 | not checked | |
| Authored mutations distinguished | 24/24 | 24/24 | 0 |
| Dev-run outcomes changed | 3 | 0 | +3 |
| tshark p50 / p95, receipt (ms) | 63.486 / 99.709 | 60.328 / 66.619 | not comparable |
| tshark p50 / p95, interleaved (ms) | 60.123 / 65.499 | 59.945 / 66.514 | +0.178 / -1.015 |
| Gate wall time (s) | 66.963 | 55.327 | +11.636 |
| Probe bytes, dev + test | 28,498 | 13,306 | +15,192 |
| Production lines | 1,537 | 754 | +783 |
| Modules | 2 | 1 | +1 |

Each receipt timed its own session (972 and 900 calls), so their runtime rows
are not comparable: on their face Full's p50 is 5.2 percent higher. The
interleaved row runs the same 900 calls alternately on both probe sets in one
container, from a scratch script that is not committed: a one-off measurement.
Three sessions gave Simplified / Full p50 of 65.022 / 65.089, 68.252 / 68.520
and 59.945 / 60.123 ms; the level moves by about 14 percent between sessions,
the per-call difference stayed within 0.4 percent in each, and the threshold
is judged on that difference. Production lines are `model_split.py` (754 to
953, of which 49 are the waivers) plus the new `witnesses.py` (584); the gate
script grew from 697 to 723 lines for the mutation label check.

The first canonical labels agreed with tshark on all six probes at their first
run. Review then found an authored mutation label no check covered
(dns-a-queries named udp-mdns, which the mutation's `dns` test never selects);
it was removed and the gate now checks mutation labels. Re-scoring the
committed dev run moved exactly C1/mei-0005, C1/mei-0006 and C4/mei-0013 from
strong exact to silent wrong (25 strong exact, 10 silent wrong); the reference
control stayed 64/64 and the mutation control 32/32.

## Witnesses

| Witness | Packet | Survivors it kills |
| --- | --- | --- |
| server-ack, server-ack-next | ACK from 443 to the client, then relative ack 5000 on that stream | dev ack-to-https port; test https-without-syn port, tcp-destination-not-https port and `< 443`; the second also ack-outside-testnet `tcp.ack == 1` |
| client-ack, client-ack-next | ACK to 443, then relative ack 5000 on that stream | dev ack-to-https `tcp.ack == 1` (the first only opens the stream) |
| keepalive-server-ack, keepalive-ack | ACK from 443 that opens its stream by acknowledging the client's sequence + 1, then a client ACK to 443 at that sequence: relative seq 0, no flag | test https-syn-or-reset `tcp.seq == 0` |
| ece-ack | ACK+ECE to 443 | dev ecn-syn-or-expiring without SYN |
| cwr-syn | SYN+CWR, no ECE | dev ecn-syn-or-expiring ece to cwr |
| ece-syn-reset | RST+ECE on cwr-syn's stream at its sequence number, relative seq 0 | dev ecn-syn-or-expiring `tcp.seq == 0` and without SYN; test https-without-syn `tcp.seq != 0`, https-syn-no-ack `tcp.seq == 0` |
| server-syn | SYN from 443 to the client | test https-syn-no-ack and https-syn-or-reset port; tcp-destination-not-https port and `< 443` |
| syn-nonzero-ack | SYN, ACK flag clear, raw ack 1 | test https-syn-no-ack `tcp.ack == 0`; dev ack-to-https `tcp.ack == 1` |
| tcp-ttl-0, tcp-ttl-2 | ACK to 443, TTL 0 and 2 | dev tcp-expiring-ttl and ecn-syn-or-expiring `== 1`, `<= 2` |
| udp-ttl-0, udp-ttl-2 | UDP to 6100, TTL 0 and 2 | dev udp-expiring-ttl and ecn-syn-or-expiring `== 1`, `<= 2` |
| udp-ttl-63, udp-ttl-128 | UDP to 6100, TTL 63 and 128 | test high-udp-normal-ttl and high-udp-testnet-normal-ttl `>= 63`, `== 64` |
| udp-to-5354 | UDP to 5354 | test all three `udp.dstport > 5354` |
| dns-mx-query | query, qtype 15 | dev dns-a-queries, aaaa-or-nxdomain; test low-port-dns-a, aaaa-or-udp-source-dns qtype ranges |
| dns-servfail | response rcode 2, server to client | dev aaaa-or-nxdomain `rcode != 0`, `> 0`; test successful-source-dns `!= 3`, `< 3`; three `ip.addr` swaps of testnet sources |
| dns-response-53-to-53 | response rcode 0, 53 to 53 | test successful-source-dns without `dstport != 53`; udp-source-testnet `ip.addr` |
| mdns-response | mDNS response rcode 0, 5353 to 5353 | test successful-source-dns without `srcport == 53`; udp-source-testnet `ip.addr` |
| dns-response-to-low-port | response rcode 0, 53 to 52 | test successful-source-dns `dstport > 53`; udp-source-testnet `ip.addr` |
| dns-query-from-low-port | A query, 52 to 53 | test dns-destination-not-source `srcport > 53` |
| dns-query-to-5352 | A query, 53 to 5352 (DNS from the source port) | test low-port-dns-a `< 5352` |
| udp-to-far-private | UDP to 10.200.3.4 | dev udp-nondns-private-destination and test private-either-endpoint destination /9, 10.1/16 |
| udp-from-far-private | UDP from 10.200.3.4 | test private-either-endpoint and source-testnet-or-private source /9, 10.1/16 |
| tcp-to-private | ACK from a server to 10.2.3.4:6100 | dev udp-nondns-private-destination without `udp`; test source-testnet-or-private `ip.addr`, private-either-endpoint destination 10.1/16, tcp-destination-not-https `< 443` |
| dns-to-private | A query to 10.2.3.5:53 | dev udp-nondns-private-destination without `!dns`; test private-either-endpoint destination 10.1/16 |
| tcp-near-testnet, udp-near-testnet | ACK or UDP from 192.0.3.9 | test 192.0.0.0/16 in all six testnet-source mutants |

Expert items on the tail are only those such packets always carry (SYN chat,
reset warning, TTL-below-5 note, nonzero-ACK-field note); no frame is
malformed or carries a TCP analysis flag. An ECN SYN-ACK later in a stream
failed in tshark (a new session, relative seq 0, reused-port note), as did a
non-SYN segment at relative seq 0 after its own side's SYN (keep-alive or
retransmission, unless a reset). A first draft waived https-syn-or-reset
`tcp.seq == 0` as not separable on that ground; review showed that when the
peer's ACK opens the stream, tshark takes the base sequence from it and shows
an unflagged ACK at relative seq 0, so the keep-alive pair kills it. Review
also replaced an ECE-only SYN (0x42), which would have scored the RFC 3168
reading of "ECN-enabled SYN" (ECE and CWR) wrong on dev, by cwr-syn: it kills
the same mutant, and `syn && ece && cwr` equals the gold on every dev probe.

One witness settles a reading on dev. Killing successful-source-dns without
`srcport == 53` takes a successful response with neither port 53, which tshark
decodes only as a protocol that shares the dns.* fields, so the tail carries an
mDNS response. fin-or-dns-response labels it, since "all DNS responses" and
the reference `dns.flags.response == 1` include mDNS; that case's
evaluator-only assumptions now say so. The answer
`tcp.flags.fin == 1 || (dns && dns.flags.response == 1)`, exact on every dev
probe without the tail, is now silent-wrong; no committed answer uses it.

## Waivers

All four are `equivalent` and hold for any packet in tshark 4.6.8's field
semantics, not only on the probes: private-either-endpoint `ip.src` to
`ip.addr` and `ip.dst` to `ip.addr` (ip.addr matches exactly where ip.src or
ip.dst does, and the other branch tests the other side);
dns-destination-not-source `udp.dstport` to `udp.port` and
successful-source-dns `udp.srcport` to `udp.port` (the other conjunct requires
the other side not to be 53). No `not_separable` waiver remains.

## Decision

`keep_full`. Full kills 61 of the 65 Simplified survivors, including all 19 on
dev, leaves 4 that are equivalent to the gold, changes no benchmark-frame label
and, in the one-off interleaved measurement, costs no measurable tshark time
per call. Scope: single-site mutants from a fixed operator set on synthetic
probes under tshark 4.6.8; a two-site near miss or a mutant outside the
operator set can still survive.

Known leftovers: the 36-spec suite on semantic-01/02/03 gets no tail and keeps
whatever near misses its probes cannot separate; it is not used for model
evaluation and its gate still passes 108/108 and 36/36. Frame 28 of
semantic-43 still decodes as malformed Manolito (udp 41170); it predates the
tail. The mDNS reading is stated only in the evaluator gold, because the dev
paraphrases stay frozen so later dev runs repeat them; new paraphrases should
name it.
Ablation 004's raw-filter evidence pins the semantic-11/17/23 hashes from
before the tail and is not reproducible from current code.
Addendum 2026-09-24: two operator families and two witness packets were added
([DNS and FIN correction](../decisions/dns-off-port-and-fin-ack.md)).
