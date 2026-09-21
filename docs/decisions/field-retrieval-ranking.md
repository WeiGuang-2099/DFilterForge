# Field retrieval ranking: named protocols and name coverage

## Problem

Over the frozen tshark 4.6.8 catalog only 1 of 16 dev items had every gold field in its
top 16. 'IPv4 TTL' surfaced mpls_echo.tlv.ilso_ipv4.ttl and aeron.setup.ttl and never
ip.ttl or tcp, so C2 and C4 would have measured the retriever, not the model.

## Change

Protocol selection. A request word names a protocol when it equals a protocol abbreviation
or the acronym (three or more characters) of a protocol display name, so IPv4 selects ip
through "Internet Protocol Version 4". In text with any capital only words with two or more
capitals count, so a sentence-initial "Find" names nothing; text without capitals lets
every word count. A field of a selected protocol gains weight 4 and its protocol tokens
count as mentioned.

Exact words. A request word equal to a token of the field abbreviation or display name adds
weight 4. Abbreviation tokens hit this way count as mentioned; display-name hits add weight
alone.

Abbreviated catalog tokens. A catalog token of three or more characters that starts with the
first letter of a longer request word and keeps its letters in order abbreviates it ("ack"
for "acknowledged"): weight 2 unless the word already scored 4, and the token counts as
mentioned.

Name coverage. score = raw * 1000 // (2 + unmatched), where unmatched counts abbreviation
tokens the request did not mention, so short fields of the named protocol beat long foreign
names; a dotted field name written verbatim in the request adds 10**9. Ties fall back to
catalog metadata as before. The constants are frozen in
[field_retrieval.py](../../src/dfilterforge/field_retrieval.py).

## Evidence

Receipts [before](evidence/field-retrieval-before.json) and
[after](evidence/field-retrieval-after.json) (retrieval-recall/1.0) were written by
[retrieval_recall.py](../../scripts/retrieval_recall.py) in the test container against the
image catalog (catalog_hash 80dc639b... in both). Their source_revision 1c64140+working-tree
labels uncommitted slices, so sources are pinned by sha256: four of five files match, and
src/dfilterforge/field_retrieval.py is 99acbd34... before and 9ba9ac79... after. Per-item
detail is written for dev only, so no receipt ever held test ranks and the before receipt
needed no reduction. The after receipt is an unedited copy of:

```text
MSYS_NO_PATHCONV=1 docker compose --profile dev run --rm -v "$(pwd -W)/src:/workspace/src:ro" -v "$(pwd -W)/tests:/workspace/tests:ro" -v "$(pwd -W)/scripts:/workspace/scripts:ro" -v "$(pwd -W)/pyproject.toml:/workspace/pyproject.toml:ro" -v "$(pwd -W)/artifacts:/workspace/artifacts" test python scripts/retrieval_recall.py --output /workspace/artifacts/retrieval/after.json --source-revision "$(git rev-parse --short HEAD)+working-tree" --include-test
cp artifacts/retrieval/after.json docs/decisions/evidence/field-retrieval-after.json
python -c "import json;b=json.load(open('docs/decisions/evidence/field-retrieval-before.json',encoding='utf-8'));a=json.load(open('docs/decisions/evidence/field-retrieval-after.json',encoding='utf-8'));f='src/dfilterforge/field_retrieval.py';assert b['source_files'][f]!=a['source_files'][f];assert 'per_item' not in b['splits']['test'] and 'per_item' not in a['splits']['test'];print('sources differ, test is aggregate only')"
```

## Results

Every cell is a receipt column (splits.dev.per_k, timing.dev), before -> after.

| Dev, 16 items | k=8 | k=16 | k=32 |
| --- | ---: | ---: | ---: |
| all_in (every gold field in context) | 1 -> 9 | 1 -> 10 | 1 -> 10 |
| macro_recall | 0.115 -> 0.708 | 0.115 -> 0.74 | 0.115 -> 0.74 |
| micro_found of 36 | 4 -> 26 | 4 -> 27 | 4 -> 27 |
| nonprotocol_found of 28 | 4 -> 18 | 4 -> 19 | 4 -> 19 |
| max_context_bytes | 1423 -> 1385 | 2846 -> 3035 | 5579 -> 5800 |
| seconds | 11.392 -> 2.242 | 11.583 -> 2.241 | 12.295 -> 2.28 |
| tracemalloc_peak_bytes | 318498 -> 5373398 | 569667 -> 5465764 | 1060154 -> 5630157 |

Each field is now tokenized once and scored only for requests sharing a word or protocol
with it, and the traced peak now includes a per-batch memo of which request words each
catalog token abbreviates. The four dev gold fields the old ranker found all stay in
context, lower in the k=32 per-item ranks: mei-0009 tcp.flags.fin 2 -> 4, mei-0010
dns.flags.response 1 -> 4 and tcp.flags.fin 3 -> 7, mei-0013 tcp.flags.syn 3 -> 4.

## Test split

Measured once for this receipt, after the rules were frozen on dev, and never used to tune
them: all_in 0/32 -> 11/32, 2/32 -> 12/32, 2/32 -> 12/32 at k=8/16/32; micro_found 6/68 ->
42/68, 10/68 -> 44/68, 13/68 -> 44/68. The receipts hold no per-item test ranks, so a test
gold field lost inside these aggregates cannot be ruled out from them. These numbers must
not guide further changes, and no test item is named here.

## Remaining misses

Nine dev gold fields are still missing at k=32. DNS query-versus-response wording:
mei-0007 ("DNS queries") and mei-0008 ("request-side DNS messages") miss dns.flags.response.
Value names: AAAA and NXDOMAIN (mei-0015), "IPv6 addresses" and "name error" (mei-0016)
reach neither dns.qry.type nor dns.flags.rcode, and mei-0008's "IPv4 address records" misses
dns.qry.type. ip.* fields when the request never says IPv4: mei-0012 ("a private 10/8
address") misses ip.dst. SYN described in other words: mei-0014 ("connection starts")
misses tcp.flags.syn.

## Decision

Keep. top_k stays 16 for the first dev run.

## Limits

The ranking is lexical only and was tuned on 16 dev items. Every timing and memory figure in
this note is a line of the committed receipts, taken in the test container against the
image catalog; no host benchmark is quoted. Dev and test come from one paraphrase generator
and one recipe world, so the test column bounds dev overfitting and says nothing about
free-form user wording, which the protocol-word rule (two or more capitals) has never been
tested against.
