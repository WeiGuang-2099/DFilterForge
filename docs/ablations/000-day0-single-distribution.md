# Ablation 000: Single Distribution Baseline

Status: keep_simplified

## Hypothesis

A single Python distribution and direct module boundaries provide the same Day
0 capabilities as separate core, API, and worker packages with less setup and
fewer dependency edges.

## Full candidate

Separate publishable packages and service scaffolds for core, API, worker, and
experiments.

## Simplified candidate

One `src/dfilterforge` distribution. API and runner are deployment boundaries,
not independently versioned domain packages.

## Evidence available at Day 0

- There is one consumer and no independent deployment cadence.
- No concurrency, persistence, or scaling measurement requires separate
  packages.
- The tshark boundary can be isolated by the runtime image without a core
  network service.

## Decision

Keep the simplified single distribution. Revisit only when two real consumers
need independent versioning or deployment.

This is a structural bootstrap ablation. Runtime and quality metrics begin with
the first executable vertical slice.
