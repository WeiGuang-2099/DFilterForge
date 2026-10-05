# Owner diagnostics, 2026-10-04 (pasted by the owner into the session)

All three were single OpenRouter requests sent by the owner from Windows PowerShell 5.1,
outside any registered run, with the prompt "Reply with OK." (no benchmark item),
max_tokens 1, reasoning {"enabled": false}, provider {"order": ["deepinfra"],
"allow_fallbacks": false}, model deepseek/deepseek-v4-pro-0813. No seed, no json mode.

## 1. First attempt

Output: `status: 401`. The key did not reach the request (the follow-up script printed the
key length and trimmed whitespace). Not about the provider.

## 2. Second attempt, after the session ended (2026-10-04)

```
status: 429
{"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"deepseek/deepseek-v4-pro-0813 is temporarily rate-limited upstream. Please retry shortly, or add your own key to accumulate your rate limits: https://openrouter.ai/settings/integrations","provider_name":"DeepInfra","is_byok":false,"provider_error_code":"engine_overloaded","limit_source":"upstream_provider_shared_pool","remedy_hint":"Retry shortly, add your own provider key (https://openrouter.ai/settings/integrations), or route to another provider with provider routing: https://openrouter.ai/docs/features/provider-routing"}},"user_id":"[redacted]"}
```

## 3. Third attempt, after the owner added a DeepSeek (official) provider key in OpenRouter BYOK

```
status: 200
{"id":"gen-1791084135-7wgkROHXIojJJ2sMtIIm","object":"chat.completion","created":1791084135,"model":"deepseek/deepseek-v4-pro-0813","provider":"DeepInfra","system_fingerprint":null,"service_tier":"default","choices":[{"index":0,"logprobs":null,"finish_reason":"length","native_finish_reason":"length","message":{"role":"assistant","content":"OK","refusal":null,"reasoning":null}}],"usage":{"prompt_tokens":8,"completion_tokens":1,"total_tokens":9,"cost":0.000013,"is_byok":false,"prompt_tokens_details":{"cached_tokens":0,"cache_write_tokens":0,"audio_tokens":0,"video_tokens":0},"cost_details":{"upstream_inference_cost":0.000013,"upstream_inference_prompt_cost":0.0000104,"upstream_inference_completions_cost":0.0000026},"completion_tokens_details":{"reasoning_tokens":0,"image_tokens":0,"audio_tokens":0}}}
```

Reading: served by DeepInfra through OpenRouter's shared pool (is_byok false, cost equals
upstream_inference_cost); the DeepSeek key sits in the DeepSeek provider row and is never
used by a DeepInfra-pinned request. One success does not show the pool is usable: the dev
round's 198 attempts (02:23-02:41 UTC) were all HTTP 429.

## Owner decision, 2026-10-04

The owner chose to move the frontier slot's repair arms to NextBit (the committed config
docs/decisions/evidence/bakeoff/configs/deepseek-v4-pro-0813_nextbit_enabled-false.json,
registered on 2026-10-01 as the frontier fallback provider), after being shown NextBit and
DeepSeek official side by side. Reasons given to the owner: same fp8 quantization label as
DeepInfra, seed supported (DeepSeek official's endpoint lists no seed, and require_parameters
is true), fixed price, config already committed, only the provider changes. Decided before
any frontier repair answer exists (dev: 0 answers in 198 attempts; test: no repair request
sent). OpenRouter endpoints API on 2026-10-04: NextBit nextbit/fp8 status 0, uptime 30m 100,
1d 99.99, prices 1.056 / 3.168 USD per million, unchanged from the committed config.
The owner did not answer whether the dev frontier round re-runs on NextBit; the maintainer
took the recommended default (re-run on dev under new run ids) and told the owner.

## 4. NextBit check after the decision, same settings as a registered call

Request: prompt 'Return the JSON object {"ok": true} and nothing else.', temperature 0, seed 17,
max_tokens 16, response_format json_object, reasoning {"enabled": false}, provider
{"order": ["nextbit"], "allow_fallbacks": false, "require_parameters": true}.

```
status: 200
{"id":"gen-1791085542-nGPIiqI34XL7MIrdVHU3","object":"chat.completion","created":1791085542,"model":"deepseek/deepseek-v4-pro-0813","provider":"NextBit","system_fingerprint":null,"service_tier":null,"choices":[{"index":0,"logprobs":null,"finish_reason":"stop","native_finish_reason":"stop","message":{"role":"assistant","content":"{\"ok\": true}","refusal":null,"reasoning":null}}],"usage":{"prompt_tokens":135,"completion_tokens":5,"total_tokens":140,"cost":0.0001584,"is_byok":false,"prompt_tokens_details":{"cached_tokens":0,"cache_write_tokens":0,"audio_tokens":0,"video_tokens":0},"cost_details":{"upstream_inference_cost":0.0001584,"upstream_inference_prompt_cost":0.00014256,"upstream_inference_completions_cost":0.00001584},"completion_tokens_details":{"reasoning_tokens":0,"image_tokens":0,"audio_tokens":0}}}
```

Reading: served by NextBit; seed and json mode accepted under require_parameters; 0 reasoning
tokens; finish stop; billed exactly at the committed config prices (135 x 1.056e-6 = 0.00014256,
5 x 3.168e-6 = 0.00001584); not BYOK, so usage.cost is the full charge. 135 prompt tokens for a
short message suggests the provider adds template tokens; this changes nothing the runner checks.
