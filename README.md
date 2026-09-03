# DFilterForge

Execution-grounded natural-language synthesis for Wireshark display filters.

DFilterForge compiles a typed packet intent into a Wireshark display filter,
validates it against a versioned field catalog, and compares candidate and
reference behavior across multiple probe captures. Results are described as
empirical observations under a pinned environment, never as global semantic
proof.

## Current status

The repository is in the first implementation slice. The recorded Evaluation
Lab demonstrates the intended evidence chain while the Docker-based tshark
runner and generated PCAP suite are being completed. See
`docs/progress.md` for verified status.

## Development

The reproducible entry point is Docker Compose:

```text
docker compose --profile pilot run --rm lab doctor
docker compose --profile dev run --rm test
docker compose --profile web-local up --build
```

The Docker daemon must be running in Linux container mode. Host Python and
tshark installations are not part of the supported execution environment.

The `Dockerfile` verifies the official Wireshark 4.6.8 source archive against
its published SHA-256 before building a tshark-only runtime. The CLI container
runs without a network, Linux capabilities, or root privileges.

## Safety boundary

The public demo accepts only repository-curated captures. Do not expose tshark
or arbitrary capture upload directly to the public internet.
