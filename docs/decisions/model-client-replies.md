# Model client replies: what a record can tell apart

Every answer of the first hosted run is stored verbatim up to 64 KiB (a larger reply keeps
no text) and scored offline, so a record that cannot tell a provider fault from a wrong
answer cannot be repaired after the money is spent.

## Question

Which provider failures must a stored completion record distinguish, and which request
controls must be recorded with it, before the first paid completion is sent?

## Settings the replay measured

    RequestSettingsV1(model_id='qwen/qwen3-8b', temperature=0.0, seed=17, max_output_tokens=2048, timeout_seconds=120.0, json_mode=True, openrouter=OpenRouterOptionsV1(provider_order=('alibaba',)))
    {"max_tokens":2048,"messages":[...],"model":"qwen/qwen3-8b","provider":{"allow_fallbacks":false,"order":["alibaba"],"require_parameters":true},"reasoning":{"enabled":false},"response_format":{"type":"json_object"},"seed":17,"temperature":0.0}
    headers: Accept, Content-Type, Authorization, User-Agent: dfilterforge-model-client

These are the replay's settings; the first dev run instead uses qwen/qwen3-32b pinned to
deepinfra, fallbacks off, --max-usd 0.25. Every parameter sent is listed in the pinned
Alibaba endpoint's supported_parameters (deepinfra's were not checked), and the after
receipt used exactly these settings, so its request_body_bytes column measures this body.
The attribution headers HTTP-Referer and X-Title are not sent: they only affect public
ranking, and the recorded pinning already names the serving provider.

## Method

[provider_reply_replay.py](../../scripts/provider_reply_replay.py) serves twelve documented
OpenRouter and OpenAI reply shapes, each with its documentation URL, plus two bounds
probes, from 127.0.0.1 and sends them through the client. No operator credential and no
external network are used; a fixed placeholder bearer token keeps the credential header
exercised. The receipts are [before](evidence/model-client-replies-1c64140.json), revision
1c64140, and [after](evidence/model-client-replies.json), revision 1c64140+A1-A9, a label
rather than a revision: those slices are not yet committed, and the commit that lands them
replaces it here, below and in the receipt with the real short sha. Each records
package_src, the source root the client came from, so the before column is provably 1c64140
code (`.worktrees/client-before/src`) and the after provably this tree (`src`).

## Measured before and after

| Measure | 1c64140 | after |
| --- | ---: | ---: |
| distinct (recorded_as, http_status, provider_error_code) over 12 replies | 3 | 10 |
| replies whose HTTP status is recorded | 0/12 | 12/12 |
| provider fault stored as a completed model answer | 1 | 0 |
| replies with provider text inside the record | 1 | 0 |
| exhausted output budget keeps finish_reason and usage | no | yes (7 of the 8 counted provenance fields) |
| reasoning returned despite the switch is visible | no | yes (reasoning_present true) |
| non-message request body bytes | 118 | 225 |
| src/dfilterforge/model_client.py lines | 451 | 486 plus 203 in completions.py |
| tests collected by each revision's own gate | 365 | 439 |
| branch coverage of that gate | 93.66 percent | 94.58 percent |
| pylint src exit status | 4 | 0 |

Byte counts come from the receipts' request_body_bytes column; reply counts cover rows 1 to
12, the documented replies; provenance counts are out of the script's eight fields.

## What changed per reply shape

- credits_exhausted, rate_limited, no_provider and no_allowed_provider were one
  indistinguishable http_error and now keep status 402, 429, 503 and 404 with
  provider_error_code from error.code.
- error_inside_http_200 was response_invalid and is now provider_error with http_status 200
  and provider_error_code 502.
- choice_finished_with_error was stored as a completed answer carrying the provider's
  partial text and is now provider_error with no text.
- reasoning_used_the_output_budget and refusal were response_invalid and are now
  empty_content keeping seven of the eight counted provenance fields, native_finish_reason
  ('length' and 'content_filter') and the usage-derived token counts among them.

## Decision

Keep. Reasoning off, provider pinning and JSON mode are opt-in recorded settings; reasoning
and refusal text are never stored; failures keep the status and usage the envelope carried.

## Open until the first real completion

- Whether deepinfra-served qwen/qwen3-32b honours reasoning.enabled=false is unchecked, so
  the first completion decides whether the rest of the pass is paid for. The call step's
  --gate-first, on by default, applies the rule below to its first completed answer and,
  when thinking was not honoured, stops before sending anything else and exits 1 with
  stop_reason thinking_not_honoured, so the gate costs one request. A fired gate ends the
  run: the provider or model is changed and a new run starts; the stopped run is never
  resumed with the gate off or continued with thinking reported as uncontrolled.
- reasoning_tokens None with reasoning_present false reads as uncontrolled, not honoured.
- The seed cannot be observed per response: DashScope's system_fingerprint is always null.
  It is reported as requested, advertised by Alibaba's endpoint (deepinfra's is unchecked)
  and sent with require_parameters true, otherwise uncontrolled.
- The Qwen3 card suggests temperature 0.7 for non-thinking mode; temperature 0 is the
  protocol's choice, and any repetition would surface as finish_reason 'length', which the
  record now keeps.

## Reproduce

```text
git worktree add .worktrees/client-before 1c64140  # from the repository root, and re-pass the --revision values below unchanged, or the diff goes dirty for a reason that is not a behaviour change
PYTHONPATH=.worktrees/client-before/src uv run --frozen --no-sync python scripts/provider_reply_replay.py --settings-module dfilterforge.model_client --revision 1c64140 --output docs/decisions/evidence/model-client-replies-1c64140.json
uv run --frozen --no-sync python scripts/provider_reply_replay.py --revision 1c64140+A1-A9 --output docs/decisions/evidence/model-client-replies.json
git worktree remove .worktrees/client-before
uv run --frozen --no-sync python -c "import json;b=json.load(open('docs/decisions/evidence/model-client-replies-1c64140.json'));a=json.load(open('docs/decisions/evidence/model-client-replies.json'));k=lambda r:(r['recorded_as'],r['http_status'],r['provider_error_code']);br=b['rows'][:12];ar=a['rows'][:12];print(len({k(r) for r in br}),len({k(r) for r in ar}),sum(r['http_status'] is not None for r in ar),sum(r['provider_text_recorded'] for r in br),sum(r['provider_text_recorded'] for r in ar),sorted({r['request_body_bytes'] for r in br}),sorted({r['request_body_bytes'] for r in ar}),b['package_src'],a['package_src'])"  # prints 3 10 12 1 0 [118] [225] .worktrees/client-before/src src
```
