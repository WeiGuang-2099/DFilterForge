"""Tests for bounded streaming retrieval from frozen field records."""

from collections.abc import Callable
from pathlib import Path
import sqlite3

import pytest

from dfilterforge.field_catalog import FieldDefinition
from dfilterforge.field_catalog import FieldType
from dfilterforge.field_retrieval import FieldRetrievalError
from dfilterforge.field_retrieval import FieldRetrievalItemV1
from dfilterforge.field_retrieval import RetrievalLimits
from dfilterforge.field_retrieval import retrieve_fields
import dfilterforge.field_retrieval as field_retrieval

_FIELD_RECORDS = (
    "P\tDomain Name System\tdns",
    "F\tQuery Name\tdns.qry.name\tFT_STRING\tdns\tBASE_NONE",
    "F\tResponse To\tdns.response_to\tFT_UINT32\tdns\tBASE_DEC",
    "F\tUnsupported Time\tframe.time\tFT_ABSOLUTE_TIME\tframe\tBASE_NONE",
    "P\tTransmission Control Protocol\ttcp",
    "F\tDestination Port\ttcp.dstport\tFT_UINT16\ttcp\tBASE_DEC",
    "F\tSource Port\ttcp.srcport\tFT_UINT16\ttcp\tBASE_DEC",
    "F\tDestination Port\tudp.dstport\tFT_UINT16\tudp\tBASE_DEC",
    "F\tInteger Clash\tbad.clash\tFT_UINT16\tbad\tBASE_DEC",
    "F\tString Clash\tbad.clash\tFT_STRING\tbad\tBASE_NONE",
    "F\tWrong Indexed Name\tactual.name\tFT_STRING\tactual\tBASE_NONE",
    "P\tInternet Protocol Version 4\tip",
    "F\tTime to Live\tip.ttl\tFT_UINT8\tip\tBASE_DEC",
    "F\tDestination Address\tip.dst\tFT_IPv4\tip\tBASE_NONE",
    "F\tAcknowledgment\ttcp.flags.ack\tFT_BOOLEAN\ttcp\t12",
    "F\tTTL\tmpls_echo.tlv.ilso_ipv4.ttl\tFT_UINT8\tmpls_echo\tBASE_DEC",
    "F\tTTL\taeron.setup.ttl\tFT_UINT32\taeron\tBASE_DEC",
    "F\tIPV4\tbacapp.IPV4\tFT_IPv4\tbacapp\tBASE_NONE",
    "P\tFind Protocol\tfind",
    "F\tDestination\teigrp.ipv4.destination\tFT_IPv4\teigrp\tBASE_NONE",
)


def _catalog(path: Path, records: tuple[str, ...] = _FIELD_RECORDS) -> None:
    with sqlite3.connect(path) as database:
        database.execute(
            "CREATE TABLE fields_records "
            "(name TEXT NOT NULL, record TEXT NOT NULL)"
        )
        database.executemany(
            "INSERT INTO fields_records VALUES (?, ?)",
            ((_record_name(record), record) for record in records),
        )
        database.execute(
            "UPDATE fields_records SET name = 'indexed.wrong' "
            "WHERE record LIKE '%Wrong Indexed Name%'"
        )


def _record_name(record: str) -> str:
    columns = record.split("\t")
    return columns[2]


def test_batch_retrieval_ranks_fields_and_preserves_opaque_ids(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite3"
    _catalog(path)
    opaque_id = "case'; DROP TABLE fields_records; --"

    results = retrieve_fields(
        path,
        (
            FieldRetrievalItemV1(
                item_id=opaque_id, intent="Show TCP destination port traffic"
            ),
            FieldRetrievalItemV1(
                item_id="dns-case", intent="Match the DNS query name"
            ),
        ),
        top_k=8,
    )

    assert tuple(result.item_id for result in results) == (
        opaque_id,
        "dns-case",
    )
    assert results[0].fields[0].abbreviation == "tcp.dstport"
    assert results[1].fields[0].abbreviation == "dns.qry.name"
    assert results[0].fields[0].field_type == FieldType.INTEGER
    assert results[0].fields[0].enum_values == ()
    assert not results[0].fields[0].enum_values_truncated
    for result in results:
        assert tuple(field.rank for field in result.fields) == tuple(
            range(1, len(result.fields) + 1)
        )
        names = {field.abbreviation for field in result.fields}
        assert "frame.time" not in names
        assert "bad.clash" not in names
        assert "actual.name" not in names
    with sqlite3.connect(path) as database:
        count = database.execute(
            "SELECT count(*) FROM fields_records"
        ).fetchone()
    assert count == (len(_FIELD_RECORDS),)


def test_ranking_is_stable_across_record_order(tmp_path: Path) -> None:
    duplicate = (
        "F\tZ Port\ttcp.port\tFT_UINT16\ttcp\tBASE_DEC",
        "F\tA Port\ttcp.port\tFT_UINT16\ttcp\tBASE_DEC",
    )
    records = _FIELD_RECORDS + duplicate
    first = tmp_path / "first.sqlite3"
    second = tmp_path / "second.sqlite3"
    _catalog(first, records)
    _catalog(second, tuple(reversed(records)))
    items = (
        FieldRetrievalItemV1(
            item_id="stable", intent="tcp.port and destination port"
        ),
    )

    forward = retrieve_fields(first, items, top_k=8)
    reversed_result = retrieve_fields(second, items, top_k=8)

    assert forward == reversed_result
    port = next(
        field for field in forward[0].fields if field.abbreviation == "tcp.port"
    )
    assert port.display_name == "A Port"


_REAL_SHAPES = (
    "F	IPV4	bacapp.IPV4	FT_IPv4	bacapp	BASE_NONE",
    "F	TCP SYN	diameter.TCP-SYN	FT_UINT32	diameter	BASE_DEC",
    "F	Message	_ws.expert.message	FT_STRING	_ws.expert	BASE_NONE",
    "P	29West Protocol	29west",
    "F	Classification	acp133.Classification	FT_UINT32	acp133	BASE_DEC",
    "F	classification	acp133.classification	FT_UINT32	acp133	BASE_DEC",
    "P	USB Device Firmware Upgrade 	usbdfu",
)
_UNPROJECTABLE = (
    "F	X Y Z	x.y.z.	FT_STRING	xyz	BASE_NONE",
    "F	   	x.y.blank	FT_STRING	xyz	BASE_NONE",
    "F	X Only	x.only	FT_STRING	xyz	BASE_NONE",
)


def test_real_catalog_name_shapes_come_back_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    _catalog(path, _REAL_SHAPES)
    intent = (
        "bacapp IPV4 diameter TCP-SYN _ws expert message 29west acp133 "
        "classification usbdfu"
    )

    results = retrieve_fields(
        path,
        (FieldRetrievalItemV1(item_id="shapes", intent=intent),),
        top_k=8,
    )

    assert {field.abbreviation for field in results[0].fields} == {
        "bacapp.IPV4",
        "diameter.TCP-SYN",
        "_ws.expert.message",
        "29west",
        "acp133.Classification",
        "acp133.classification",
        "usbdfu",
    }
    upgrade = next(
        field for field in results[0].fields if field.abbreviation == "usbdfu"
    )
    assert upgrade.display_name == "USB Device Firmware Upgrade "


def test_fields_that_cannot_enter_a_prompt_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    _catalog(path, _UNPROJECTABLE)

    results = retrieve_fields(
        path,
        (FieldRetrievalItemV1(item_id="skip", intent="x y z blank only xyz"),),
        top_k=1,
    )

    assert len(results[0].fields) == 1
    assert results[0].fields[0].abbreviation == "x.only"


def _ranked(path: Path, intent: str, top_k: int = 16) -> list[str]:
    results = retrieve_fields(
        path,
        (FieldRetrievalItemV1(item_id="item", intent=intent),),
        top_k=top_k,
    )
    return [field.abbreviation for field in results[0].fields]


def test_named_protocols_rank_their_own_short_fields_first(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite3"
    _catalog(path)

    names = _ranked(
        path, "Keep only TCP packets whose IPv4 TTL is 1 or lower.", top_k=4
    )

    # IPv4 selects ip through the acronym of "Internet Protocol Version 4".
    assert names[:2] == ["ip.ttl", "tcp"]
    assert "mpls_echo.tlv.ilso_ipv4.ttl" not in names[:2]
    assert "aeron.setup.ttl" not in names[:2]


def test_abbreviated_catalog_tokens_match_full_words(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    _catalog(path)

    names = _ranked(
        path, "Find acknowledged TCP segments on destination port 443"
    )

    assert names[0] == "tcp.dstport"
    # The catalog token "ack" abbreviates the request word "acknowledged".
    assert "tcp.flags.ack" in names


def test_only_acronym_shaped_words_select_protocols_in_cased_text(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite3"
    _catalog(path)

    cased = _ranked(path, "Find IPv4 destination traffic")
    lowered = _ranked(path, "find ipv4 destination traffic")

    # Cased text: only IPv4 has two capitals, so "Find" names no protocol.
    assert cased.index("ip.dst") < cased.index("eigrp.ipv4.destination")
    assert cased.index("eigrp.ipv4.destination") < cased.index("find")
    assert "find" not in cased[:2]
    # Text without capitals: every word may name a protocol.
    assert lowered.index("find") < lowered.index("eigrp.ipv4.destination")


def test_query_without_matching_words_returns_an_empty_context(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite3"
    _catalog(path)

    results = retrieve_fields(
        path, (FieldRetrievalItemV1(item_id="none", intent="xyzzy"),)
    )

    assert results[0].item_id == "none"
    assert results[0].fields == ()


def test_unprojectable_rows_are_skipped_without_projecting_every_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    top_k = 4
    ports = tuple(
        f"F\tPort {index}\tport{index:02d}.port\tFT_UINT16\t"
        f"port{index:02d}\tBASE_DEC"
        for index in range(40)
    )
    # Best-scored row (it names the requested protocol) with a blank display
    # name, which the prompt contract rejects.
    blank = "F\t   \tport.blank\tFT_UINT16\tport\tBASE_DEC"
    path = tmp_path / "catalog.sqlite3"
    _catalog(path, (*_FIELD_RECORDS, *ports, blank))
    projectable: Callable[[FieldDefinition], bool] = getattr(
        field_retrieval, "_projectable"
    )
    score: Callable[..., int] = getattr(field_retrieval, "_score")
    projections: list[bool] = []
    positive_scores: list[int] = []

    def counting_projectable(field: FieldDefinition) -> bool:
        outcome = projectable(field)
        projections.append(outcome)
        return outcome

    def counting_score(*arguments: object) -> int:
        value = score(*arguments)
        if value > 0:
            positive_scores.append(value)
        return value

    monkeypatch.setattr(field_retrieval, "_projectable", counting_projectable)
    monkeypatch.setattr(field_retrieval, "_score", counting_score)

    names = _ranked(path, "port", top_k=top_k)

    assert len(positive_scores) > 3 * top_k
    assert len(projections) <= 3 * top_k
    assert False in projections
    assert "port.blank" not in names
    assert names == ["port00.port", "port01.port", "port02.port", "port03.port"]


def test_batch_uses_one_constant_streaming_select(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "catalog.sqlite3"
    _catalog(path)
    statements: list[str] = []
    connect = sqlite3.connect

    def traced_connect(
        database: str, *, uri: bool = False
    ) -> sqlite3.Connection:
        connection = connect(database, uri=uri)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(field_retrieval.sqlite3, "connect", traced_connect)
    intent = "tcp'; SELECT private FROM secrets; -- destination port"

    retrieve_fields(
        path,
        (
            FieldRetrievalItemV1(item_id="one", intent=intent),
            FieldRetrievalItemV1(item_id="two", intent="DNS query name"),
        ),
    )

    field_selects = [
        statement
        for statement in statements
        if statement.startswith("SELECT name, record FROM fields_records")
    ]
    assert len(field_selects) == 1
    protocol_selects = [
        statement
        for statement in statements
        if statement.startswith("SELECT record FROM fields_records")
    ]
    assert len(protocol_selects) == 1
    assert all(intent not in statement for statement in statements)


@pytest.mark.parametrize(
    ("item", "code"),
    [
        (
            FieldRetrievalItemV1(item_id="bytes", intent="a" * 4097),
            "query_too_long",
        ),
        (
            FieldRetrievalItemV1(
                item_id="tokens", intent=" ".join("a" for _ in range(65))
            ),
            "query_too_many_tokens",
        ),
        (
            FieldRetrievalItemV1(item_id="empty", intent="    "),
            "query_empty",
        ),
    ],
)
def test_query_limits_fail_before_catalog_access(
    tmp_path: Path, item: FieldRetrievalItemV1, code: str
) -> None:
    with pytest.raises(FieldRetrievalError) as caught:
        retrieve_fields(tmp_path / "missing.sqlite3", (item,))

    assert caught.value.code == code


@pytest.mark.parametrize(
    ("top_k", "code"), [(0, "top_k_invalid"), (33, "top_k_too_large")]
)
def test_top_k_is_bounded(top_k: int, code: str, tmp_path: Path) -> None:
    with pytest.raises(FieldRetrievalError) as caught:
        retrieve_fields(
            tmp_path / "missing.sqlite3",
            (FieldRetrievalItemV1(item_id="item", intent="tcp"),),
            top_k=top_k,
        )

    assert caught.value.code == code


def test_duplicate_item_ids_are_rejected_before_catalog_access(
    tmp_path: Path,
) -> None:
    items = (
        FieldRetrievalItemV1(item_id="same", intent="tcp"),
        FieldRetrievalItemV1(item_id="same", intent="dns"),
    )

    with pytest.raises(FieldRetrievalError) as caught:
        retrieve_fields(tmp_path / "missing.sqlite3", items)

    assert caught.value.code == "duplicate_item_id"


def test_serialized_field_context_is_a_best_first_bounded_prefix(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite3"
    _catalog(path)
    items = (
        FieldRetrievalItemV1(
            item_id="context", intent="TCP destination port traffic"
        ),
    )
    full = retrieve_fields(path, items, top_k=8)
    first = full[0].fields[0]
    one_field_bytes = len(first.model_dump_json().encode("utf-8")) + 2

    limited = retrieve_fields(
        path,
        items,
        top_k=8,
        limits=RetrievalLimits(max_context_bytes=one_field_bytes),
    )

    assert limited[0].fields == (first,)
    serialized_size = (
        sum(
            len(field.model_dump_json().encode("utf-8"))
            for field in limited[0].fields
        )
        + max(0, len(limited[0].fields) - 1)
        + 2
    )
    assert serialized_size <= one_field_bytes


def test_empty_batch_needs_no_catalog_and_missing_catalog_is_sanitized(
    tmp_path: Path,
) -> None:
    path = tmp_path / "missing.sqlite3"
    assert retrieve_fields(path, ()) == ()

    with pytest.raises(FieldRetrievalError) as caught:
        retrieve_fields(
            path,
            (FieldRetrievalItemV1(item_id="item", intent="tcp"),),
        )

    assert caught.value.code == "catalog_unavailable"
