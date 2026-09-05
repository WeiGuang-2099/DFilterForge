# Curated PCAP fixtures

Only synthetic or redistribution-compatible captures may be committed here.
Every capture must have a matching semantic spec containing its SHA-256,
provenance, license, split, and review state. Public Demo never accepts arbitrary
uploads.

The pilot generator uses only Python's standard library to construct nine
complete Ethernet/IPv4 captures. It writes three independently specified
semantic tasks, each with probe seeds 17, 42, and 2026:

| Task | Matching packets | Near-wrong witness |
| --- | --- | --- |
| `tcp-syn-no-ack` | SYN set, ACK clear, including ECN SYN | SYN+ACK packets defeat testing SYN alone |
| `dns-udp-query` | DNS questions over UDP | DNS responses defeat testing only protocol presence; TCP questions test transport scope |
| `udp-destination-53` | UDP destination port 53 | Source-only port 53 packets defeat `udp.port == 53` |

Generate through the Docker CLI into the mounted artifact directory:

```sh
docker compose --profile pilot run --rm lab fixtures generate \
  --output-dir /workspace/artifacts/fixtures
```

The resulting directory contains `manifest.json`, `captures/{probe_id}.pcap`,
`specs/{task_id}.json`, and `intents/{task_id}.json`. The manifest records file
SHA-256 values, seeds, packet recipes, manually authored expected packet sets,
and near-wrong packet sets. The semantic specs carry MIT licensing, synthetic
provenance, the `pilot` split, and a single source review state. Generation does
not claim successful tshark execution: the live integration tests verify the
labels against pinned tshark 4.6.8 separately.

All addresses and DNS names are synthetic documentation/example values; no
network packets are sent. Repeated generation has fixed timestamps, ordering,
headers, checksums, and JSON serialization. Each seed changes the packet mix,
packet ordering, and endpoints. Labels are defined in the packet plans before
execution, independently from the compiler and the reference filters.
