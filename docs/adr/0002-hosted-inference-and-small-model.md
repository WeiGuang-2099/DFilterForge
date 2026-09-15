# ADR 0002: Hosted inference for baselines, a small local model for training

Status: accepted, 2026-09-15

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
