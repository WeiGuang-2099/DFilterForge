# First dev run: what qwen3-32b measured and what it did not

## Run

[dev-qwen3-32b-2026-09-21](../results/dev-qwen3-32b-2026-09-21/scored/summary.md): 64
requests (16 dev items in C1 to C4) called from 21622f8 on 2026-09-23, prompts frozen on
2026-09-21. All 64 answers were served as qwen/qwen3-32b by DeepInfra, finished with stop
and reported 0 reasoning tokens. Price-derived and provider-reported spend were both
0.0059 USD. Scored offline in the lab container with code 21622f8; `score --check`
reproduces it with no differences.

| Condition | Strong exact | Silent-wrong | Invalid | Abstained | Malformed |
| --- | ---: | ---: | ---: | ---: | ---: |
| C1 filter | 10 | 2 | 3 | 1 | 0 |
| C2 filter + retrieval | 9 | 4 | 1 | 2 | 0 |
| C3 typed IR | 1 | 0 | 15 | 0 | 0 |
| C4 typed IR + retrieval | 8 | 1 | 5 | 1 | 1 |

Counts are items out of 16. With 8 cases no comparison can reach 10 discordant cases, so
every verdict is inconclusive by construction. An independent audit re-derived every outcome
and every number in the summary from the committed files and found no scoring error. It
found the problems below, which change how the numbers can be read.

## Findings

The typed-IR prompt never says how a value is written. It shows
`{"kind":"predicate","field":F,"operator":O,"value":V}` and leaves V undefined, while the
binder accepts only a JSON number for an integer field and only true or false for a boolean
field. C3 wrote all 24 integer and boolean values as strings, and every one of the 20 typed
invalids (C3 15, C4 5) contains a quoted integer or boolean. C4 wrote 14 of 20 correctly
because its retrieved fields carry field_type. Applying the obvious type coercion to the
stored answers and executing them on the probes gives C3 9 and C4 10 strong exact instead of
1 and 8. That is an estimate, not a result, but it means C4 - C3 (+0.438) here mostly
measures whether value types were shown, not whether retrieval found the right names.

Three strong exact answers are wrong and passed only because no probe packet separates them
from the reference. C1/mei-0005 uses tcp.port == 443 for "sent to port 443"; C1/mei-0006
uses tcp.ack == 1, the acknowledgment number, for the ACK flag, and the fixture writes ack
number 1 exactly when the ACK flag is set; C4/mei-0013 drops SYN, and the only recipe with
ECE is a SYN. Each filter is broader than the reference yet matched every probe. Counted as
wrong, C1 is 8 and C4 is 7 strong exact. The test captures come from the same recipes and
share these gaps.

C1 errors are mostly names. Three filters invent Wireshark names (ipv4.ttl, dns.qr and
dns.qtype, tcp.options.ecn.present) and are otherwise correct. Two are semantic: a UDP or
PGM transport limit on a request for any transport, and AND for OR with SYN dropped. One
abstains to ask for a direction the request never mentions.

Retrieval traded loud errors for quiet ones. C2 fixed two invented names (mei-0004,
mei-0013) and the abstention (mei-0010), but mei-0008 went from invalid to silent-wrong and
mei-0015 from strong exact to silent-wrong. Neither item had any gold field retrieved, and
the model used a similar answer-record field listed near the top (dns.a, dns.aaaa). All four
C2 silent-wrongs sit on items missing a gold field. C2 is strong exact on 9 of the 10 items
with every gold field retrieved and 0 of the other 6, against 7 and 3 for C1, so coverage
and item difficulty are confounded.

Smaller contract gaps: the all/any minimum of two children appears only as `[N,N,...]`
(C4/mei-0014 is malformed for two one-child groups); the `assumptions` key is undefined and
all 64 replies copy user_assumptions; "use only those field names" has no rule for an
incomplete list and is not enforced (C4/mei-0004 used ip.proto from outside its list);
retrieved enum_values are always empty.

The summary's Run settings print provider_changed true. That is a false alarm: the pinned
slug deepinfra is compared case-sensitively with the served name DeepInfra. Its Cost USD
column is the 16-item total, and the silent-wrong (exec) cell does not show its denominator
(C3 rests on 1 executable item and 647 of 1,000 resamples). None of these changes a metric.

## Consequences

- This run stays as published: it measures prompt v1 as frozen, including its gaps.
- C3 compile validity and C4 - C3 are not evidence about the model or about retrieval.
- Strong exact overstates semantic correctness by up to two items in C1 and one in C4.
- The probe gaps must be closed with witness recipes before the test split is frozen; the
  stored answers can then be re-scored offline with no new request.
