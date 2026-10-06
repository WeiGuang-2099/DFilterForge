"""The packet list of a capture, as the pinned tshark shows it.

Reads, for every frame, the columns of Wireshark's packet list: number,
relative time, source, destination, protocol, length and info, with name
resolution off and the runner's isolated profile and environment. The web
site draws its ladder diagram and its packet list from these rows, so it
never runs tshark or ships packet bytes.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Literal

from dfilterforge.errors import DFilterForgeError
from dfilterforge.runner import TsharkRunner

# The packet list's columns as tshark fields: the Source, Destination,
# Protocol and Info columns are tshark's own column fields.
FIELDS: tuple[str, ...] = (
    "frame.number",
    "frame.time_relative",
    "_ws.col.def_src",
    "_ws.col.def_dst",
    "_ws.col.protocol",
    "frame.len",
    "_ws.col.info",
)
_TIME = re.compile(r"[0-9]{1,9}\.[0-9]{9}")
_LENGTH = re.compile(r"[1-9][0-9]{0,5}")

# Where a frame goes relative to the probe's client address: from it, to
# it, or between two other hosts.
Direction = Literal["out", "in", "other"]


class PacketListError(DFilterForgeError, RuntimeError):
    """A packet list tshark printed in a form this module does not read."""


@dataclass(frozen=True, slots=True)
class PacketRow:
    """One frame's packet-list columns, as tshark prints them."""

    n: int
    time: str
    src: str
    dst: str
    protocol: str
    length: int
    info: str


def _row(line: str, number: int) -> PacketRow:
    cells = line.split("\t")
    if len(cells) != len(FIELDS):
        raise PacketListError("columns_invalid", f"Frame {number} columns")
    n, time, src, dst, protocol, length, info = cells
    if n != str(number) or not _TIME.fullmatch(time):
        raise PacketListError("columns_invalid", f"Frame {number} number")
    if not _LENGTH.fullmatch(length) or not (src and dst and protocol):
        raise PacketListError("columns_invalid", f"Frame {number} columns")
    return PacketRow(number, time, src, dst, protocol, int(length), info)


class PacketListRunner(TsharkRunner):
    """The pinned runner, reading a capture's packet list."""

    def packet_list(self, capture: Path) -> tuple[PacketRow, ...]:
        """Returns every frame's columns, numbered from 1 in order.

        Raises:
            RunnerError: As the runner raises for a capture it cannot run.
            PacketListError: With code ``columns_invalid`` for a row that
                is not one frame's seven columns in order.
        """
        self.version()
        output, _ = self._execute(
            [
                "-n",
                "-r",
                str(capture),
                "-T",
                "fields",
                "-E",
                "separator=/t",
                "-E",
                "quote=n",
                "-E",
                "occurrence=f",
                *(argument for name in FIELDS for argument in ("-e", name)),
            ],
            frame_limit=self.limits.max_frames,
        )
        try:
            text = output.decode("utf-8")
        except UnicodeDecodeError:
            raise PacketListError(
                "columns_invalid", "tshark printed text that is not UTF-8"
            ) from None
        lines = text.removesuffix("\n").split("\n") if text else []
        return tuple(_row(line, n) for n, line in enumerate(lines, 1))


def client_address(rows: Sequence[PacketRow]) -> str:
    """The address seen in most frames, as source or destination.

    Ties go to the lowest address as text, so the choice never depends on
    frame order.
    """
    seen = Counter(address for row in rows for address in (row.src, row.dst))
    if not seen:
        raise PacketListError("columns_invalid", "A capture has no frames")
    return min(seen, key=lambda address: (-seen[address], address))


def direction(row: PacketRow, client: str) -> Direction:
    """Whether a frame leaves the client, reaches it, or passes it by."""
    if row.src == client:
        return "out"
    return "in" if row.dst == client else "other"


def packet_table(capture: Path, runner: PacketListRunner) -> dict[str, object]:
    """A capture's client address and every frame's columns and direction."""
    rows = runner.packet_list(capture)
    client = client_address(rows)
    return {
        "client": client,
        "frames": [
            {**asdict(row), "direction": direction(row, client)} for row in rows
        ],
    }
