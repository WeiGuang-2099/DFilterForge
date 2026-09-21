# Frozen tshark 4.6.8 inventory

`tshark-4.6.8.catalog.sqlite3.gz` is the complete inventory extracted inside
the project Docker image. It preserves every field/protocol report row, every
value report row (including exact, range, true/false and extended records),
the executable version/build report and isolated runtime preferences/decoders.
The upstream inventory comes from Wireshark 4.6.8 (GPL-2.0-or-later).

The Docker build generates its own read-only SQLite catalog using the same
binary and profile as execution. This archive records the measured baseline;
it is not silently substituted for a newly built environment's inventory.
See [ablation 002](../../docs/ablations/002-frozen-field-catalog.md) for
byte-for-byte reproducibility and runtime binding results.

This archive predates the current image freeze. Its recorded `catalog_hash`
and row counts differ from the catalog the Docker build freezes: `ce22f217`
against `80dc639b`, and 1,709,597 value rows against 1,709,593, with
`fields_records` holding the same 266,369 rows in a different order. Retrieval
streams fields in name order and breaks ties on field metadata, and the dev
prompts prepared from either inventory are byte-identical, so the archive is
not re-exported; `prepare.json` records whichever inventory a preparation used.
Open the archive on the host only: it expands to 299,319,296 bytes in the
temporary directory, more than a container's `/tmp` holds, so containers read
`/opt/dfilterforge/catalog.sqlite3`.

Export without loading the whole catalog into memory:

```text
docker compose --profile dev run --rm --volume "${PWD}/artifacts:/workspace/artifacts" test python scripts/export_catalog.py --output /workspace/artifacts/tshark-4.6.8.catalog.sqlite3.gz
```

The output path must not already exist. The gzip stream has no timestamp or
original filename. Runtime compilation queries only fields referenced by the
IR and compares version/configuration and supplied definitions with the frozen
inventory; it does not hash the complete 299 MB database on every invocation.
