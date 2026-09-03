# Code Style

## Python

- Follow the Google Python Style Guide.
- Format with Pyink at 80 columns and sort imports with the isort Google profile.
- Use Pyright strict typing and Pylint for production modules.
- Public APIs require Google-style docstrings; avoid comments that repeat code.
- Prefer pure functions for compilation, validation, diffing, and metrics.

## TypeScript

- Follow the Google TypeScript Style Guide and keep strict mode enabled.
- Do not use production `any`, `@ts-ignore`, or unexplained non-null assertions.
- Use semantic HTML first and preserve visible keyboard focus.
- Use URL state for shareable selections, query state for server data, and local
  state for transient UI. Do not add a global store without measured need.

## Abstractions

An abstraction must isolate a real external boundary, support two real
implementations, own an independent lifecycle, or remove stable duplication.
Otherwise use the concrete function or class.
