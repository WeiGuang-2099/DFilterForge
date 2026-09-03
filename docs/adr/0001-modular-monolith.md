# ADR 0001: Use a Modular Monolith

Status: accepted

## Context

The pilot needs a compiler, field catalog, tshark execution, evaluation, and a
Web presentation. They share versioned contracts but do not require independent
deployment or scaling during feasibility work.

## Decision

Use one Python distribution with dependency direction from application edges
to a framework-independent core. The Web is a separate build artifact. Split
deployment images only where the tshark security boundary requires it.

Do not create repository, service, factory, event-bus, plugin, or microservice
layers without two real implementations or a measured external-boundary need.

## Consequences

The project has fewer concepts, one contract source, and simpler replay. If
real concurrency or persistence evidence appears, the relevant boundary can be
extracted with an ablation report.
