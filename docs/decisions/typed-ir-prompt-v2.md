# Typed-IR prompt v2: say how each value is written

## Problem

The first dev run's typed-IR system message showed `"value":V` and never said what V is
([first dev run](first-dev-run.md)). The binder accepts only a JSON number on an integer
field and only true or false on a boolean one, so C3 wrote all 24 integer and boolean values
as strings, 11 of its 15 invalids were type mismatches, and C4 - C3 mostly measured whether
a prompt showed value types.

## Change

The only model-visible change in 33ad868 is the typed-IR system message: how each bound type
is written, which operators take which types, that a protocol takes only exists, and that
all and any take two or more children. It names no field. The display-filter prompt is
unchanged. The commit also keeps every system prompt version, so scoring rebuilds each
committed prompt under the version that made it and the first run still re-scores.

## Evidence

[dev-qwen3-32b-v2-2026-09-23](../results/dev-qwen3-32b-v2-2026-09-23/scored/summary.md): 64
requests called from d7b9e7f on 2026-09-23 with the first run's settings, all served as
qwen/qwen3-32b by DeepInfra with 0 reasoning tokens, 0.0065 USD. Both runs are scored
against the same witness-corrected gold (hash 57db1369ae6f). Items out of 16, first run ->
v2:

| Condition | Strong exact | Silent-wrong | Invalid | Malformed | Abstained |
| --- | ---: | ---: | ---: | ---: | ---: |
| C1 filter | 8 -> 9 | 4 -> 3 | 3 -> 3 | 0 -> 0 | 1 -> 1 |
| C2 filter + retrieval | 9 -> 9 | 4 -> 4 | 1 -> 1 | 0 -> 0 | 2 -> 2 |
| C3 typed IR | 1 -> 8 | 0 -> 1 | 15 -> 6 | 0 -> 1 | 0 -> 0 |
| C4 typed IR + retrieval | 7 -> 10 | 2 -> 5 | 5 -> 0 | 1 -> 0 | 1 -> 1 |

Quoted integer or boolean values fell from 30 (C3 24, C4 6) to 0; the only v2 string values
are CIDR strings. C3's two remaining type mismatches (mei-0005, mei-0006) put true on
tcp.ack, the acknowledgment number, for the ACK flag: a wrong field that is silent-wrong
even as 1. Of C3's 7 new strong exact items, 5 changed only their value encoding; mei-0003
also changed fields, and mei-0001 moved from an invented `tcp.present` to `tcp` with exists.
C4 gained mei-0001 and mei-0010 by encoding alone and mei-0016 by a different field choice.
No typed item that was strong exact, silent-wrong or abstained in the first run changed
outcome.

C4 silent-wrong rose from 2 to 5 because three answers that failed the type or arity check
now execute: mei-0007 (`dns || mdns`, a new error), mei-0015 (`dns.aaaa` for the AAAA
question, v1's error behind a quoted rcode) and mei-0014 (of v1's two one-child groups, one
is unwrapped and the other gains a second child `tcp` that absorbs its ECE test). All three
sit on items where retrieval missed a gold field. One C3 answer (mei-0014) still wrote a
one-child any despite the new rule.

C4 - C3 went from +0.375 (cases 4 vs 0) to +0.125 [-0.125, 0.438] (cases 2 vs 1). The
post-hoc coercion estimate in the first note (C3 8, C4 9) matched the C3 total by
coincidence: v2 gained mei-0001 and lost mei-0010 through field changes that coercion holds
fixed, and C4 reached 10 through mei-0016.

## Repeatability

C1 and C2 are a repeat: their prepared files are byte-identical in both runs, and every
answer records the same model and provider, a null system fingerprint and finish stop.
Answer text is identical on 12 of 16 C1 items and 14 of 16 C2 items; outcome on 15 and 16.
The one flip is C1/mei-0005, `tcp.port == 443` becoming `tcp.dstport == 443`, so C1 8 -> 9
is rerun variation, not a prompt effect. The seed is sent but uncontrolled, and nothing
recorded explains the difference. The same applies to the first note's item-level readings:
each answer is one draw. Typed answers are about twice as long and their rerun rate was not
measured.

## What it shows and what it does not

It shows that stating value encodings removed the encoding failure under this prompt: 30
quoted values to 0, C3 compile validity 1 to 9 and C4 5 invalids to 0. It also shows that
compile validity is not correctness: C4's executed answers are silent-wrong 5 of 15 times.

It does not show a contract or retrieval effect. With 8 cases no comparison can reach 10
discordant cases, every v2 comparison interval spans zero, and rerun variation cannot be
excluded for a gap of one or two items. C4 still sees each retrieved field's type and C3
does not, so a small type-hint channel remains in C4 - C3. Nothing here reaches past one
model, one provider route, 8 dev cases and their frozen paraphrases.

## Decision

Keep prompt v2 for new typed-IR runs; v1 stays registered only so the first run re-scores.
The v2 run is published beside the first, not in its place, and no single-item difference
between the runs is cited as an effect.

Open, for the next gold correction under `docs/protocol.md`: C3/mei-0011
(`udp.port != 53 && ip.dst == 10.0.0.0/8`) is exact only because no probe sends UDP to 10/8
that tshark decodes as DNS on a port other than 53; scored silent-wrong it would give C3 7.
No probe holds a FIN+ACK segment, so a filter requiring FIN with ACK clear scores exact; no
v2 answer relies on it. Both are near misses outside the fixed mutant operator set.
