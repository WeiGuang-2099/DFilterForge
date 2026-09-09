"""Export the frozen Docker inventory as a deterministic gzip archive."""

from __future__ import annotations

import argparse
import gzip
from pathlib import Path
import shutil

from dfilterforge.catalog_runtime import DEFAULT_CATALOG_PATH


def main() -> None:
    """Stream the catalog to an explicitly named output without rehashing it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.source.open("rb") as source:
        with arguments.output.open("xb") as target:
            with gzip.GzipFile(
                filename="", fileobj=target, mode="wb", mtime=0
            ) as archive:
                shutil.copyfileobj(source, archive)
    print(f"Catalog bytes: {arguments.source.stat().st_size}")
    print(f"Archive bytes: {arguments.output.stat().st_size}")


if __name__ == "__main__":
    main()
