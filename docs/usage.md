# Usage

Run every command from the repository root; Docker must be in Linux container
mode; in Git Bash prefix Docker commands with `MSYS_NO_PATHCONV=1`.

## Development

The reproducible entry point is Docker Compose:

```text
docker compose --profile pilot run --rm lab doctor
docker compose --profile dev build test
docker compose --profile dev run --rm test
SOURCE_COMMIT=$(git rev-parse HEAD) docker compose --profile web-local up --build
```

The last command serves the site at `http://127.0.0.1:3000/DFilterForge/`;
page links name `SOURCE_COMMIT`, so the build refuses to run without it.

The Docker daemon must be running in Linux container mode. tshark execution,
the catalog freeze and scoring all run in containers. Split generation, field
retrieval and prompt preparation are pure Python and also run on the host with
`uv run --frozen`. The hosted model call must run on the host, because the
lab, test and dev containers all run with `network_mode: none`.

The `Dockerfile` verifies the official Wireshark 4.6.8 source archive against
its published SHA-256 before building a tshark-only runtime. The CLI container
runs without a network, Linux capabilities, or root privileges.

## Three local execution cases

Generate nine deterministic captures using seeds 17, 42, and 2026:

```text
docker compose --profile pilot build lab
docker compose --profile pilot run --rm lab fixtures generate --output-dir /workspace/artifacts/pilot
```

The generated task IDs are `tcp-syn-no-ack`, `dns-udp-query`, and
`udp-destination-53`. Each has independent packet labels and a near-wrong
filter witness. Run a case with the source revision you are evaluating:

```text
docker compose --profile pilot run --rm lab evaluate-live --spec /workspace/artifacts/pilot/specs/tcp-syn-no-ack.json --candidate-ir /workspace/artifacts/pilot/intents/tcp-syn-no-ack.json --capture-root /workspace/artifacts/pilot/captures --run-id syn-example --created-at 2026-09-04T00:00:00Z --code-revision YOUR_REVISION --output /workspace/artifacts/pilot/syn.receipt.json
docker compose --profile pilot run --rm lab replay-run --receipt /workspace/artifacts/pilot/syn.receipt.json --spec /workspace/artifacts/pilot/specs/tcp-syn-no-ack.json --candidate-ir /workspace/artifacts/pilot/intents/tcp-syn-no-ack.json --capture-root /workspace/artifacts/pilot/captures
```

Replace the task ID to run the DNS and UDP cases. `evaluate-live` executes
both reference and candidate filters and rejects a reference that disagrees
with the independent labels. Candidate differences remain visible in the
receipt. Its environment sidecar records measured binary and runner identity;
it explicitly lists unmeasured container and shared-library properties.
The summary includes a packet-set hash that excludes runtime measurements.
For a packet diff, the trace sidecar records actual tshark matches for every
candidate and canonical leaf predicate on counterexample frames. It does not
record packet payloads or inferred field values. `replay-run` requires the
specification, the curated capture root, and either the candidate IR or
`--receipt-filter`, which replays the receipt's own display filter. It
re-executes the reference and the candidate, plus any needed predicate filters
when given an IR. Its replay decision uses exact frame tuples and ignores
runtime and stored hash claims.

The runner snapshots at most 16 MiB per capture, allows at most five seconds
per tshark process, limits output and frame count, and kills the process group
on completion or failure. Display filters are passed as a single argument with
`shell=False`. These limits complement the container resource restrictions.

## Frozen field catalog

The Docker build freezes the complete tshark field and value inventory in
`/opt/dfilterforge/catalog.sqlite3`, including the actual version and isolated
dissector configuration. SQLite is part of Python's standard library. The
compiler reads the fields referenced by an intent from that inventory, keeping
memory bounded without restricting validation to a protocol whitelist.

`compile` and `evaluate-live` validate fields, operators, literal types, and the
catalog's runtime binding before any capture execution. A supplied catalog is
checked against the frozen environment. The domain compiler remains independent
of file storage and subprocess execution.

```text
docker compose --profile pilot run --rm lab catalog freeze --output /workspace/artifacts/catalog.sqlite3
docker compose --profile pilot run --rm lab compile --intent-ir /workspace/artifacts/pilot/intents/tcp-syn-no-ack.json
```

The SQLite catalog is generated inside the pinned image. Rebuilding and
extracting twice in the same environment must produce identical catalog bytes;
this checks reproducibility without adding repeated whole-file work to
compilation.

## Semantic benchmark

The pilot suite contains 36 authored specifications with an independent
semantic review, each with three probes and a near-wrong filter. Packet labels
come from named synthetic packet recipes independently of the IR and
display-filter strings. The suite includes explicit counterexamples for field
absence, direction, Boolean flags, numeric boundaries, DNS, subnets, and nested
logic. Generated manifests record `ready` status, `reviewed` review status, and
the review provenance. These are curated pilot fixtures, not a held-out model
test set.

```text
docker compose --profile dev run --rm --volume "${PWD}/artifacts:/workspace/artifacts" test python scripts/benchmark_gate.py --phase suite --source-revision YOUR_REVISION --output-dir /workspace/artifacts/benchmark
docker compose --profile dev run --rm --volume "${PWD}/artifacts:/workspace/artifacts" test python scripts/benchmark_gate.py --phase stability --source-revision YOUR_REVISION --output-dir /workspace/artifacts/benchmark
```

The stability phase executes all 50 byte-distinct captures against all 150
different filter strings twice (15,000 tshark calls). It compares exact frame
tuples and writes progress after each capture. The extra boundary filters are
runtime stress inputs, not additional authored specifications. Different filter
strings do not imply different semantics.

An interrupted stability run can resume from a matching local checkpoint. Use
`--restart-stability` to discard an existing checkpoint explicitly.

CI runs the semantic oracle and mutation checks. The longer complete stability
matrix is an explicit release measurement. Passing these synthetic gates does
not measure model compile validity or silent-wrong rate.

## Hosted model run

`RUN` below is `dev-qwen3-32b-v2-2026-09-23`: qwen/qwen3-32b on the dev split
via deepinfra, fallbacks off, with the second typed-IR prompt; the date records
when its prompts were frozen (UTC). Its C1 and C2 prompts are byte-identical to
the first run's, `dev-qwen3-32b-2026-09-21`, which is scored and committed.
The [protocol](protocol.md) defines what is measured.

1. Build the test image the prompts are prepared in.
2. Prepare the prompts. Done for `RUN`: `publish` refuses a new `prepare.json`,
   so restore a lost `artifacts/model-eval/RUN` by copying
   `docs/results/RUN/prepare.json` and `prepared/` into it instead.
3. Set `DFILTERFORGE_MODEL_API_KEY` in your shell only. It is never written to
   a file, and `publish` refuses any file holding it or a token-shaped string.
4. Save the third line below as `artifacts/call-config.json` (ignored) with
   the provider's prices filled in; prices cannot be added after the run.
5. Call on the host. On exit 1, read the printed `stop_reason`. `null`: re-run
   with `--resume`. `fatal_http`: fix the key or credit, then resume. `budget`:
   the 0.25 USD cap cannot cover the next request; the run cannot be published.
   `thinking_not_honoured` (`--gate-first`, on by default) ends the run: move
   `artifacts/model-eval/RUN/runs/RUN` out of `runs/`, change the provider or
   model (a new model needs a new `RUN`) and call again without `--resume`.
6. Publish the run beside the frozen prompts.
7. Score offline in the lab container, then commit `docs/results/RUN`.

```text
docker compose --profile dev build test
docker compose --profile dev run --rm --volume "${PWD}/artifacts:/workspace/artifacts" test python scripts/model_run.py prepare --catalog /opt/dfilterforge/catalog.sqlite3 --output-dir /workspace/artifacts/model-eval/RUN --source-revision YOUR_REVISION
{"endpoint_url": "https://openrouter.ai/api/v1/chat/completions", "settings": {"model_id": "qwen/qwen3-32b", "openrouter": {"provider_order": ["deepinfra"], "allow_fallbacks": false, "reasoning": "enabled_false"}}, "prices": {"usd_per_million_input": INPUT_PRICE, "usd_per_million_output": OUTPUT_PRICE, "source": "PRICE_SOURCE"}}
uv run --frozen python scripts/model_run.py call --prepare-dir artifacts/model-eval/RUN --run-id RUN --config artifacts/call-config.json --max-usd 0.25 --source-revision YOUR_REVISION
uv run --frozen python scripts/model_run.py publish --run-dir artifacts/model-eval/RUN/runs/RUN --output docs/results/RUN
docker compose --profile pilot build lab
docker compose --profile pilot run --rm lab score --run-dir /workspace/results/RUN --code-revision YOUR_REVISION
```

Step 5 is the only command here that needs a key and spends money; every other
command is exercised by the test suite or by CI. The
[reference](results/dev-qwen3-32b-v2-2026-09-23/control-reference/summary.md)
and [mutation](results/dev-qwen3-32b-v2-2026-09-23/control-mutation/summary.md)
control scores are the scorer's measured baseline; the model's numbers are in
`docs/results/RUN/scored/summary.md`, where C2 and C4 also print how often
retrieval listed every gold field. `--check` (plus `--control reference`
or `mutation`) reproduces any of them without a key.

## Self-served runs on Modal

Qwen/Qwen3-1.7B and its SFT adapters are served and trained on Modal by
`modal/serve_vllm.py` and `modal/train_sft.py`; the [self-served
note](decisions/self-served-runs.md) holds the stack, the run ids and the
rules. Every command below runs in Windows PowerShell 5.1 at the root of the
owner's checkout, on `main` once this lands. Commands marked paid start a
GPU; nothing else spends money.

Estimates, not measurements: an L4 container costs about USD 1/h (USD 0.80
for the GPU, the rest CPU and memory); a request takes about 5 s (the hosted
runs averaged about 800 prompt and 130 to 260 answer tokens, an L4 decodes
this model at roughly 70 to 90 tokens per second, and the call paces at 1 s);
a server start takes 2 to 5 minutes and the server idles 5 minutes before it
scales to zero.

| Step | GPU time | USD |
| --- | ---: | ---: |
| Deploy (image build, CPU only) | none | under 0.05 |
| One dev pass, 160 requests, with start and idle | about 20 min | about 0.30 |
| One test pass, 448 requests, with idle | about 45 min | about 0.75 |
| Train one seed, 3 epochs over 1,299 rows | about 1 h | about 1.00 |
| Whole plan: four rows on dev and test, three seeds trained | about 7 h | about 7 |

### Once

1. Install the Modal client and log in. Set a workspace budget of USD 10 on
   https://modal.com/settings/usage (Usage and Billing); the Starter plan's
   USD 30 monthly credit covers the whole plan.
2. Make the server's key: create a Proxy Auth Token on
   https://modal.com/settings/proxy-auth-tokens and keep its ID (`wk-...`)
   and secret (`ws-...`, shown only once) in your password manager. The key
   the call step sends is the two joined by a period,
   `wk-<id>.ws-<secret>`. Modal's proxy answers every request without it
   with 401 before a container starts, so nobody else can start the GPU.
3. Deploy, fill in the call config with the URL the deploy prints
   (`https://<workspace>--dfilterforge-vllm-server.us-east.modal.direct`):
   replace `WORKSPACE` in `$url` below with your part of it, then stop the
   app. Each session deploys it again and stops it at the end.
4. Copy the committed prompt sets to where the call step reads them.

```powershell
uv tool install modal==1.6.1
modal setup
modal deploy modal/serve_vllm.py
$url = "https://WORKSPACE--dfilterforge-vllm-server.us-east.modal.direct"
New-Item -ItemType Directory -Force artifacts/modal | Out-Null
(Get-Content modal/call-config.json -Raw).Replace("https://WORKSPACE--dfilterforge-vllm-server.us-east.modal.direct", $url) | Set-Content -Encoding ascii -NoNewline artifacts/modal/qwen3-1.7b.json
foreach ($id in "dev-qwen3-1.7b-2026-10-07", "test-qwen3-1.7b-2026-10-07") { New-Item -ItemType Directory -Force "artifacts/model-eval/$id" | Out-Null; Copy-Item "docs/results/$id/prepare.json", "docs/results/$id/prepared" "artifacts/model-eval/$id" -Recurse -Force }
modal app stop dfilterforge-vllm
```

The deploy builds the image once and starts no GPU until a request with
the key arrives. The last line is required: no app stays deployed between
sessions.

### Each session

First, without the key in the shell, run each call you will send this
session: it must stop at `api_key_missing` (exit 2), which proves that the
run id, cap, prompts, source digests, freeze admission and config pass the
call step's own checks; the call step has no `--dry-run`. Then deploy, read
the key, set `$url` again, wake the server (paid: it starts the GPU) and
wait until `/v1/models` lists the served names. The first start downloads
the weights (about 4 GB).

```powershell
$env:PYTHONIOENCODING = "utf-8"
uv run --frozen python scripts/model_run.py call --prepare-dir artifacts/model-eval/dev-qwen3-1.7b-2026-10-07 --run-id dev-qwen3-1.7b-2026-10-07 --config artifacts/modal/qwen3-1.7b.json --max-usd 0.05 --source-revision (git rev-parse --short HEAD) --gate-first --max-attempts 3 --min-interval-seconds 1.0
modal deploy modal/serve_vllm.py
$url = "https://WORKSPACE--dfilterforge-vllm-server.us-east.modal.direct"
$secure = Read-Host -AsSecureString "Proxy key wk-<id>.ws-<secret>"
$env:DFILTERFORGE_MODEL_API_KEY = [System.Net.NetworkCredential]::new("", $secure).Password
Remove-Variable secure
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$h = @{ Authorization = "Bearer $env:DFILTERFORGE_MODEL_API_KEY" }
$m = $null; $t = [Diagnostics.Stopwatch]::StartNew()
while (-not $m -and $t.Elapsed.TotalMinutes -lt 15) { try { $m = Invoke-RestMethod "$url/v1/models" -Headers $h -TimeoutSec 30 } catch { Write-Host "$([int]$t.Elapsed.TotalSeconds) s: $($_.Exception.Message)"; if ([int]$_.Exception.Response.StatusCode -in 401, 403, 404) { break }; Start-Sleep 15 } }
if ($m) { $m.data.id; Invoke-RestMethod "$url/version" -Headers $h } else { Write-Host 'Not ready. Read modal app logs dfilterforge-vllm, then run modal app stop dfilterforge-vllm.' }
```

Replace `WORKSPACE` in `$url` as in the Once block. The wait prints each
failed try. It stops at once on 401 or 403 (a wrong key) and on 404 (a
wrong `$url` or no deploy), since waiting cannot fix those, and gives up
after 15 minutes, the server's own startup limit. When it prints `Not
ready`, read the server's log with `modal app logs dfilterforge-vllm`
(Ctrl+C ends it) and end the session as below before anything else.
Otherwise the last line prints the vLLM version, which must be 0.21.0;
give it to the maintainer with the run.

### Base model: dev, then test

One command per run (paid). Exit 0 means the run is complete. On exit 1,
read the printed `stop_reason`: `null` means items are pending after
transient failures (a scaled-down server answers 503); wake the server
again and re-run the same command with `--resume`. Send the test run only
after the dev run is complete; the note fixes that rule.

```powershell
uv run --frozen python scripts/model_run.py call --prepare-dir artifacts/model-eval/dev-qwen3-1.7b-2026-10-07 --run-id dev-qwen3-1.7b-2026-10-07 --config artifacts/modal/qwen3-1.7b.json --max-usd 0.05 --source-revision (git rev-parse --short HEAD) --gate-first --max-attempts 3 --min-interval-seconds 1.0
uv run --frozen python scripts/model_run.py call --prepare-dir artifacts/model-eval/test-qwen3-1.7b-2026-10-07 --run-id test-qwen3-1.7b-2026-10-07 --config artifacts/modal/qwen3-1.7b.json --max-usd 0.10 --source-revision (git rev-parse --short HEAD) --gate-first --max-attempts 3 --min-interval-seconds 1.0
```

Publish each complete run beside its committed prompts and score it offline
in the lab container (no key, no GPU), as for a hosted run:

```powershell
uv run --frozen python scripts/model_run.py publish --run-dir artifacts/model-eval/dev-qwen3-1.7b-2026-10-07/runs/dev-qwen3-1.7b-2026-10-07 --output docs/results/dev-qwen3-1.7b-2026-10-07
docker compose --profile pilot build lab
docker compose --profile pilot run --rm lab score --run-dir /workspace/results/dev-qwen3-1.7b-2026-10-07 --code-revision (git rev-parse --short HEAD)
```

Repeat the first and last lines for `test-qwen3-1.7b-2026-10-07`.

End every session with these two lines, also after a failed run: the first
stops the server at once, where scale to zero would bill 5 more idle
minutes, and leaves no app deployed until the next session's deploy. Then
read the session's GPU time and cost on Modal's usage page and give them to
the maintainer for the note.

```powershell
modal app stop dfilterforge-vllm
Remove-Item Env:DFILTERFORGE_MODEL_API_KEY
```

### Training: three seeds

One command per seed (paid), one after another, so the first fills the
weight cache the others read. `--detach` keeps a run going if the shell
disconnects. Each writes `sft-v1-s<seed>/` (adapter, log, run manifest) to
the `dfilterforge-adapters` volume; the last line copies a run into the
ignored `artifacts/sft/`.

```powershell
modal run --detach modal/train_sft.py --seed 17
modal run --detach modal/train_sft.py --seed 42
modal run --detach modal/train_sft.py --seed 2026
modal volume get dfilterforge-adapters sft-v1-s17 artifacts/sft
```

A failed seed is trained again only after
`modal volume rm -r dfilterforge-adapters sft-v1-s<seed>`.

### Adapters: dev, then test

Open a session as above, whose deploy serves every adapter trained by
then, and wait until `$m.data.id` lists `qwen3-1.7b-sft-s17` and the
others. The maintainer first seeds and commits `docs/results/<run id>/` for
each adapter run from the base row's directory, as the note says. Each
seed then gets its own config, and its calls are the base model's with its
run id and config, for example for seed 17 (paid):

```powershell
(Get-Content modal/call-config.json -Raw).Replace("https://WORKSPACE--dfilterforge-vllm-server.us-east.modal.direct", $url).Replace('"Qwen/Qwen3-1.7B"', '"qwen3-1.7b-sft-s17"') | Set-Content -Encoding ascii -NoNewline artifacts/modal/qwen3-1.7b-sft-s17.json
uv run --frozen python scripts/model_run.py call --prepare-dir artifacts/model-eval/dev-qwen3-1.7b-2026-10-07 --run-id dev-qwen3-1.7b-sft-s17-2026-10-07 --config artifacts/modal/qwen3-1.7b-sft-s17.json --max-usd 0.05 --source-revision (git rev-parse --short HEAD) --gate-first --max-attempts 3 --min-interval-seconds 1.0
uv run --frozen python scripts/model_run.py call --prepare-dir artifacts/model-eval/test-qwen3-1.7b-2026-10-07 --run-id test-qwen3-1.7b-sft-s17-2026-10-07 --config artifacts/modal/qwen3-1.7b-sft-s17.json --max-usd 0.10 --source-revision (git rev-parse --short HEAD) --gate-first --max-attempts 3 --min-interval-seconds 1.0
```

Seeds 42 and 2026 follow with `s42` and `s2026` in the names.
