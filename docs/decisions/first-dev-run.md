# First dev run: what qwen3-32b measured and what it did not

## Run

[dev-qwen3-32b-2026-09-21](../results/dev-qwen3-32b-2026-09-21/scored/summary.md): 64
requests (16 dev items in C1 to C4) called from 21622f8 on 2026-09-23, prompts frozen on
2026-09-21. All 64 answers were served as qwen/qwen3-32b by DeepInfra, finished with stop
and reported 0 reasoning tokens. Price-derived and provider-reported spend were both
0.0059 USD. Scored offline in the lab container with code 21622f8, re-scored after the
report fix below, then re-scored in place with code 7bafd27+working-tree after the gold
correction below; `score --check` reproduces all three trees with no differences. The
answers are unchanged. The summary before the gold correction is in git history at 1b5d230.

| Condition | Strong exact | Silent-wrong | Invalid | Abstained | Malformed |
| --- | ---: | ---: | ---: | ---: | ---: |
| C1 filter | 8 | 4 | 3 | 1 | 0 |
| C2 filter + retrieval | 9 | 4 | 1 | 2 | 0 |
| C3 typed IR | 1 | 0 | 15 | 0 | 0 |
| C4 typed IR + retrieval | 7 | 2 | 5 | 1 | 1 |

Counts are items out of 16. With 8 cases no comparison can reach 10 discordant cases, so
every verdict is inconclusive by construction. An independent audit re-derived every outcome
and every number in the pre-correction summary from the committed files and found no
scoring error. It found the problems below, which change how the numbers can be read.

## Gold correction

Three answers first scored strong exact were wrong and passed only because no probe packet
separated them from the reference. C1/mei-0005 uses tcp.port == 443 for "sent to port 443";
C1/mei-0006 uses tcp.ack == 1, the acknowledgment number, for the ACK flag, and relative
numbering shows ack 1 on the first ACK of every stream; C4/mei-0013 drops SYN, and the only
recipe with ECE was a SYN. The test captures shared these gaps.

Every dev and test probe now ends in 31 witness packets after its benchmark frames
([ablation 005](../ablations/005-probe-witnesses.md)). An ACK from port 443 separates
mei-0005; a second ACK on one stream (relative ack 5000) and a SYN with a nonzero ACK field
separate mei-0006; an ECE ACK and an ECE reset separate mei-0013. All three are now
silent-wrong and no other outcome changed: 25 strong exact and 10 silent-wrong overall,
against 28 and 7 before. The reference control stays strong exact on 64/64 and the mutation
control silent-wrong on 32/32; only their hashes and frames changed.

One witness settles a reading the dev probes had left open. A test near miss (a successful
response without source port 53) needs a response with neither port 53, so the tail carries
an mDNS response, and fin-or-dns-response counts it, since "all DNS responses" and its
reference `dns.flags.response == 1` include mDNS; the case's evaluator-only assumptions now
say so. `tcp.flags.fin == 1 || (dns && dns.flags.response == 1)`, exact before, is now
scored silent-wrong on dev. No committed answer uses it; the frozen paraphrases do not name
mDNS.

The three were one class, not three accidents. Of 182 single-site mutants of the 24
canonical IRs (field swaps, flags written as numbers, off-by-one bounds, subnet edits,
dropped conditions, DNS code ranges), 65 matched the gold on every probe of their split
before the correction, dev 19 and test 46. After it, 4 do, all on test, all equivalent to
the gold for any packet and waived with a written reason (ip.addr or udp.port where the
other side is already constrained). Reference filters, canonical IRs and authored mutations
agree with their authored labels on all six probes (144 of 144 each), and
`scripts/probe_adequacy.py` fails CI on any mismatch or unwaived survivor.

Updated on 2026-09-24 by the [DNS and FIN correction](dns-off-port-and-fin-ack.md): the probes
now end in 33 witness packets and the gate runs 192 mutants with the same 4 waivers. This run
was re-scored in place with code 75ccc59+working-tree against gold 8a061589fe6c, and no
outcome changed. Its C3/mei-0011 answer, once coerced, is the v2 filter that the correction
made silent-wrong, so the coercion estimate below becomes C3 7.

## Findings

The typed-IR prompt never says how a value is written. It shows
`{"kind":"predicate","field":F,"operator":O,"value":V}` and leaves V undefined, while the
binder accepts only a JSON number for an integer field and only true or false for a boolean
field. C3 wrote all 24 integer and boolean values as strings, and every one of the 20 typed
invalids (C3 15, C4 5) contains a quoted integer or boolean. C4 wrote 14 of 20 correctly
because its retrieved fields carry field_type. Applying the obvious type coercion to the
stored answers and executing them on the corrected probes gives C3 8 and C4 9 strong exact
instead of 1 and 7 (9 and 10 before the correction). That is an estimate, not a result, but
it means C4 - C3 (+0.375) here mostly measures whether value types were shown, not whether
retrieval found the right names.

C1 errors are split between invented names and semantics. Three filters invent Wireshark
names (ipv4.ttl, dns.qr and dns.qtype, tcp.options.ecn.present) and are otherwise correct.
Four are semantic: a UDP or
PGM transport limit on a request for any transport, AND for OR with SYN dropped, and the
two probe-gap answers above. One abstains to ask for a direction the request never
mentions.

Retrieval traded loud errors for quiet ones. C2 fixed two invented names (mei-0004,
mei-0013), the abstention (mei-0010) and both probe-gap answers (mei-0005, mei-0006), but
mei-0008 went from invalid to silent-wrong and mei-0015 from strong exact to silent-wrong.
Neither item had any gold field retrieved, and the model used a similar answer-record field
listed near the top (dns.a, dns.aaaa). All four C2 silent-wrongs sit on items missing a
gold field. C2 is strong exact on 9 of the 10 items with every gold field retrieved and 0 of
the other 6, against 5 and 3 for C1, so coverage and item difficulty are confounded.

Smaller contract gaps: the all/any minimum of two children appears only as `[N,N,...]`
(C4/mei-0014 is malformed for two one-child groups); the `assumptions` key is undefined and
all 64 replies copy user_assumptions; "use only those field names" has no rule for an
incomplete list and is not enforced (C4/mei-0004 used ip.proto from outside its list);
retrieved enum_values are always empty.

The first rendering of the summary printed provider_changed true. That was a false alarm:
the pinned slug deepinfra was compared case-sensitively with the served name DeepInfra. Its
Cost USD column was the 16-item total, and the silent-wrong (exec) cell hid its denominator
(C3 rests on 1 executable item and 647 of 1,000 resamples). The report now matches slugs to
names, prints cost per item, the executed count and thin intervals, and says when every
comparison is inconclusive by construction. That re-score changed no outcome or metric.

## Consequences

- The answers stay as published: the run measures prompt v1 as frozen, including its gaps.
  Only the gold changed, and the corrected score replaced the old one in place.
- C3 compile validity and C4 - C3 are not evidence about the model or about retrieval.
- Strong exact is now checked against every single-site mutant of the gold from a fixed
  operator set (`dfilterforge.mutants`); the four survivors are equivalent to the gold and
  named in `model_split.MUTANT_WAIVERS`. A near miss outside that operator set can still
  pass.
- Any later gold correction follows the rule in `docs/protocol.md`: justified without
  reference to which answers flip, every flipped item listed, and a frozen test score kept
  beside the corrected one rather than replaced.
