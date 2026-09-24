# Gold correction: DNS off port 53 and FIN with ACK

## Problem

The [v2 audit](typed-ir-prompt-v2.md) left two probe gaps open. No dev or test probe held a UDP
packet to 10.0.0.0/8 that tshark decodes as DNS on a port other than 53, so C3/mei-0011
`udp.port != 53 && ip.dst == 10.0.0.0/8` scored strong exact. No probe held a FIN segment with
any other flag set, so reading FIN as the whole flag field, `tcp.flags == 1`, matched the gold's
FIN frames exactly. Neither near miss was in the gate's operator set, so the gate passed.

## Specification

Case udp-nondns-private-destination asks for "non-DNS UDP packets", and its second phrasing for
"UDP traffic not decoded as DNS" (`a1d3724:src/dfilterforge/model_split.py:348-351`). Its reference is
`udp && !dns && ip.dst == 10.0.0.0/8`, and the pilot family it draws on is "UDP without the
unicast DNS protocol" (`benchmark.py:363`). DNS here is what the dissector finds, not a port
number, and pinned tshark 4.6.8 finds it off port 53: its `dns_udp` heuristic is enabled
(`tshark -G heuristic-decodes`). Case fin-or-dns-response asks for "TCP FIN packets", which
include a FIN that also carries ACK, as an ordinary close does. Neither reading changed; only
the packets that test them did.

## Change

- Gate, `dfilterforge.mutants`: two operator families. protocol-as-port writes a protocol test
  as its usual port on either side (`dns` as `udp.port == 53` or `tcp.port == 53`; `mdns` and
  `http` likewise, which no current case uses). flag-as-byte writes a set TCP flag as the whole
  flag field equal to that bit, as the pilot suite's own mutations `tcp.flags == 2`, `16` and
  `4` read SYN, ACK and RST (`benchmark.py:196-244`). The mutant count goes from 182 to 192.
- Probes, `dfilterforge.witnesses`: two packets appended to every probe's tail, 31 becoming 33.
  `dns-query-to-private-low` is an A query from the client's port 6100 to 10.2.3.6 port 52;
  neither port has a tshark dissector, so the heuristic decodes it as DNS. `server-fin-ack` is
  FIN with ACK from port 443 to the client. Benchmark frames and the first 31 witnesses keep
  their bytes and frame numbers.
- Labels: fin-or-dns-response's canonical set gains the FIN witness, the only edit by hand.
  Every other membership follows from the witness families, and the gate checks all of them
  with tshark.

The operator families were chosen after the gaps were known. protocol-as-port was written
after the v2 audit had read C3/mei-0011, which is why this note names that answer.
flag-as-byte repeats mutations the pilot suite authored before any model ran.

## Gate evidence

[Before](evidence/dns-fin-gate-before.json), report mode: the 192-mutant set against the
31-witness probes (source files as at 75ccc59, except `mutants.py`). Three survivors have no
waiver:

- dev fin-or-dns-response `(tcp.flags == 1 || dns.flags.response == true)`
- dev udp-nondns-private-destination `(udp && !(udp.port == 53) && ip.dst == 10.0.0.0/8)`
- test ack-outside-testnet `(tcp.flags == 16 && !(ip.src == 192.0.2.0/24))`, which no audit had
  named; its gold counts ACK segments from outside TEST-NET-1, and no such segment carried a
  second flag.

[After](evidence/dns-fin-gate-after.json), strict mode at a1d3724: 192 mutants executed, 0
survivors without a waiver, the same 4 equivalent waivers. Reference, canonical IR and
authored mutation match their labels on all six probes. The pinned-tshark decode test checks
both new packets on all six probes: no malformed frame and no TCP analysis flag, and the FIN
carries only its chat and its closing note. With the tail, `udp.port != 53`,
`!(udp.dstport == 53)` and the two-site `tcp.flags.fin == 1 && tcp.flags.ack == 0` all differ
from the gold on every dev probe.

## Re-score

Both committed runs and their controls were re-scored in place with code
75ccc59+working-tree: the sources of 6079cec plus the mutant families of a1d3724, which scoring
does not use. The gold hash moves from 57db1369ae6f to 8a061589fe6c. Stored answers, prompts
and run manifests are unchanged, and `score --check` reproduces all six outputs.

One item flipped and none went the other way: v2 C3/mei-0011, strong exact to silent-wrong.
The first run's C3/mei-0011 was invalid and stays invalid, and no first-run outcome changed.
The reference control stays strong exact on 64/64 and the mutation control silent-wrong on
32/32 in both runs.

| Run | Condition | Strong exact | Silent-wrong | Silent-wrong of executed |
| --- | --- | ---: | ---: | ---: |
| v2 | C3 typed IR | 8 -> 7 | 1 -> 2 | 1/9 -> 2/9 |

Everything else is unchanged: the first run's strong exact stays 8, 9, 1, 7 in C1 to C4, and v2
stays 9, 9 and 10 in C1, C2 and C4. In v2, C4 - C3 moves from +0.125 [-0.125, 0.438] (cases
2 vs 1) to +0.188 [0.000, 0.500] (2 vs 0), still inconclusive with 2 discordant cases. The other
comparisons do not move.

## Limits

- Whether an mDNS packet to 10/8 counts as non-DNS is still untested: no mDNS packet goes to
  10/8. The reading is an evaluator-only assumption (`a1d3724:src/dfilterforge/model_split.py:75`).
  The rewritten test requests state it; the dev requests stay unchanged so the published runs
  keep their text.
- A two-site near miss is outside a single-site operator set. The FIN witness separates
  `fin && !ack` today, but no gate rule requires it to.
- The DNS witness relies on the heuristic staying enabled in the pinned profile. If a tshark or
  profile change disabled it, the decode test would fail.

## Decision

Keep both families and both packets. The dev gold is corrected in place under
`docs/protocol.md`. The test split is not frozen and has no answers, so there is no test score
to publish beside the correction.
