"""The packet list of a curated capture, read by the pinned tshark.

The capture is regenerated from the model split, so the columns below are
the ones the web site's ladder and packet list show for the Reel's pick.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from dfilterforge.model_split import generate_model_split
from dfilterforge.packet_list import client_address
from dfilterforge.packet_list import packet_table
from dfilterforge.packet_list import PacketListError
from dfilterforge.packet_list import PacketListRunner
from dfilterforge.packet_list import PacketRow


@pytest.fixture(name="capture", scope="module")
def fixture_capture(tmp_path_factory: pytest.TempPathFactory) -> Path:
    split = generate_model_split(tmp_path_factory.mktemp("split"))
    return next(
        probe.capture_path
        for probe in split.probes
        if probe.probe_id == "semantic-37"
    )


def test_the_table_lists_every_frame_with_its_columns_and_direction(
    capture: Path,
) -> None:
    table = packet_table(capture, PacketListRunner())

    frames = cast(list[dict[str, object]], table["frames"])
    assert len(frames) == 60
    assert table["client"] == "192.0.2.137"
    # The frame that disproves the Reel's pick: a FIN from port 443.
    assert frames[59] == {
        "n": 60,
        "time": "0.059000000",
        "src": "198.51.100.60",
        "dst": "192.0.2.137",
        "protocol": "TCP",
        "length": 60,
        "info": "443 \u2192 41196 [FIN, ACK] Seq=1 Ack=1 Win=8192 Len=0",
        "direction": "in",
    }
    assert [frames[n - 1]["direction"] for n in (1, 17, 19)] == [
        "out",
        "in",
        "other",
    ]


def test_the_client_is_the_address_in_most_frames_and_ties_go_low() -> None:
    def row(n: int, src: str, dst: str) -> PacketRow:
        return PacketRow(n, "0.000000000", src, dst, "UDP", 60, "")

    assert client_address([row(1, "10.0.0.9", "10.0.0.2")]) == "10.0.0.2"
    assert (
        client_address(
            [row(1, "10.0.0.9", "10.0.0.2"), row(2, "10.0.0.9", "10.0.0.3")]
        )
        == "10.0.0.9"
    )
    with pytest.raises(PacketListError) as caught:
        client_address([])
    assert caught.value.code == "columns_invalid"
