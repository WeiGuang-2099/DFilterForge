# ADR 0002: Hosted inference for baselines, a small local model for training

Status: accepted, 2026-09-15; amended 2026-10-18

## Context

The earlier pilot plan self-hosted a 27B model on a rented A100 for prompt
baselines and left training as a conditional smoke test. It required weeks of
gate work before the first model call, and its budget could not pay for any
training result. The oracle, catalog, runner, trace and replay are done; the
missing evidence is a model number.

## Decision

- Prompt-condition baselines (C1 to C4 in `docs/protocol.md`) run against
  hosted OpenAI-compatible endpoints. Every raw completion is stored and
  scored offline in the no-network lab container.
- Post-training uses a 1.7B-class open model with QLoRA-SFT and
  verifier-labelled DPO, three seeds each, plus a continued-SFT control, on a
  rented 48 GB GPU. GRPO is measured (reward-variance gate) but not trained.
- The web application is a static export generated from receipts; no page
  number may be typed by hand, and a CI test compares rendered numbers with
  the scored summary.
- The first measured model number must be committed before any GPU spend,
  and the hosted page must exist before training starts.

## Consequences

Total spend stays under 50 USD. The evaluation harness gains an evaluee
within the first week. The 27B pilot, its staged budget, its agent-wave plan
and the gate ladder are archived under `tasks/archive/`. Results are
comparisons of the same small model trained versus untrained; no claim is
made against larger hosted models.

## Amendment, 2026-10-18

Written after seed 2026's test scores were known (C4 strong exact 0.475
[0.338, 0.600], against 0.438 to 0.850 for the hosted test rows) and
before seeds 17 and 42 were scored. With 40 ready test cases, an interval
around the difference to a much larger model can contain 0, and a page
that calls that "indistinguishable" reads as parity. The 1.7B rows may
stand beside the hosted test rows only under these rules, which replace
the last sentence above:

- The number shown is the paired difference: the three-seed adapter mean's
  test C4 strong exact minus a hosted row's, over the 40 ready cases, with
  the interval from the shared vectors (`docs/protocol.md`, Training
  rules). No single seed is set against a hosted model.
- Every hosted test row is listed: the three slot winners, and
  qwen/qwen3-32b by its A/A pass A. None is chosen or left out.
- An interval that contains 0, or fewer than 10 discordant cases, reads
  "not separable on these 40 cases", never "matches", "on par",
  "equivalent" or "indistinguishable". Only an interval that excludes 0
  with at least 10 discordant cases reads as higher or lower.
- The 1.7B rows stand in their own band and never enter the /board
  ranking.
- Each such comparison is followed by the closed-world sentence: the
  adapters were trained on compositions of exactly the 38 predicates the
  dev and test gold uses, so test asks them for unseen compositions of
  seen atoms, not for unseen fields, operators or values.
