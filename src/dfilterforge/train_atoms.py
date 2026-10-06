"""The closed world of training predicates and their plain wordings.

The pool is exactly the 38 predicates the ready dev and test gold uses, over
22 fields; ``tests/test_train_split.py`` holds it equal to them. Training
therefore teaches unseen compositions of seen atoms, never new fields,
operators or values. That closed world is a disclosed design choice.

Each atom carries two wordings and, where one exists, the request slot a
non-ready variant leaves open with the wording that leaves it open. A
wording is a plural verb phrase that completes "packets that ...". A
wording starting with "are" is negated with "are not", any other with "do
not", so no wording may itself start with a negation.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import cast, TypeAlias

from dfilterforge.intent_ir import MissingSlot
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.intent_ir import ScalarValue

_Value: TypeAlias = ScalarValue | tuple[ScalarValue, ...] | None

# One atom per header line: field, operator and a JSON value (or nothing).
# The next line holds its two wordings; the third the slot a non-ready
# variant drops and the wording that drops it, or "-" when none does.
# {host} and {app} are filled from HOSTS and APPS.
_TABLE = """
tcp exists
  carry TCP | are TCP segments
  protocol: use the transport protocol {app} relies on
udp exists
  carry UDP | are UDP datagrams
  protocol: use whichever transport {app} picked
dns exists
  carry unicast DNS (not mDNS) | are unicast DNS messages
  -
dns.flags.rcode eq 0
  have DNS reply code 0 (NOERROR) | carry a DNS rcode of 0
  value: have the DNS reply code we talked about
dns.flags.rcode eq 3
  have DNS reply code 3 (NXDOMAIN) | carry a DNS rcode of 3
  value: carry the DNS error code from the incident report
dns.flags.response eq false
  are DNS or mDNS queries | have the DNS response flag clear
  -
dns.flags.response eq true
  are DNS or mDNS responses | have the DNS response flag set
  -
dns.qry.type eq 1
  ask for A records (type 1) | carry a DNS question of type A
  value: ask for the record type we talked about
dns.qry.type eq 28
  ask for AAAA records (type 28) | carry a DNS question of type AAAA
  value: ask for the DNS record type named in the ticket
ip.addr in_subnet "192.0.2.0/24"
  have an endpoint in 192.0.2.0/24 | involve 192.0.2.0/24 on either side
  direction: have 192.0.2.0/24 on the one side we agreed on
ip.dst in_subnet "10.0.0.0/8"
  go to an address in 10.0.0.0/8 | have a destination inside 10/8
  address: go to {host}
ip.src in_subnet "10.0.0.0/8"
  come from 10.0.0.0/8 | have a source address in 10/8
  address: come from {host}
ip.src in_subnet "192.0.2.0/24"
  come from 192.0.2.0/24 | have a source address in TEST-NET-1
  direction: have TEST-NET-1 at the one end we picked
ip.ttl ge 64
  have an IPv4 TTL of 64 or more | carry a TTL of at least 64
  value: have a TTL at or above the threshold from the runbook
ip.ttl gt 1
  have an IPv4 TTL above 1 | carry a TTL greater than 1
  value: have a TTL above the floor we agreed on
ip.ttl le 1
  have an IPv4 TTL of 1 or less | carry a TTL no higher than 1
  value: have a TTL at or under the limit we set
ip.ttl lt 64
  have an IPv4 TTL below 64 | carry a TTL under 64
  value: have a TTL under the cutoff from last week
tcp.dstport eq 443
  go to TCP port 443 | have TCP destination port 443
  port: go to the TCP port {app} listens on
tcp.dstport ne 443
  are TCP segments not sent to port 443 | use a TCP destination port besides 443
  port: are TCP segments not sent to the port {app} listens on
tcp.flags.ack eq false
  are TCP segments with ACK clear | carry TCP with the ACK bit off
  -
tcp.flags.ack eq true
  have the TCP ACK flag set | carry TCP with the ACK bit on
  field: have the TCP flag we discussed set
tcp.flags.cwr eq true
  have the TCP CWR flag set | carry TCP with the CWR bit on
  field: carry TCP with the flag from the ticket turned on
tcp.flags.ece eq false
  are TCP segments with ECE clear | carry TCP with the ECE bit off
  -
tcp.flags.ece eq true
  have the TCP ECE flag set | carry TCP with the ECE bit on
  field: have the TCP flag from the bug report set
tcp.flags.fin eq true
  have the TCP FIN flag set | carry TCP with the FIN bit on
  field: carry TCP with the flag we mentioned turned on
tcp.flags.reset eq true
  have the TCP RST flag set | carry TCP with the reset bit on
  field: have the TCP flag from the alert set
tcp.flags.syn eq false
  are TCP segments with SYN clear | carry TCP with the SYN bit off
  -
tcp.flags.syn eq true
  have the TCP SYN flag set | carry TCP with the SYN bit on
  field: have the TCP flag we flagged earlier set
tcp.len eq 0
  carry a TCP payload of length 0 | are TCP segments with zero payload bytes
  -
tcp.port eq 443
  use TCP port 443 on either side | have 443 as TCP source or destination port
  direction: use TCP port 443 in the one direction we care about
tcp.srcport eq 443
  come from TCP port 443 | have TCP source port 443
  port: come from the TCP port {app} answers on
udp.dstport eq 53
  go to UDP port 53 | have UDP destination port 53
  port: go to the UDP port {app} listens on
udp.dstport gt 5353
  go to a UDP port above 5353 | have a UDP destination port over 5353
  port: go to a UDP port above the one {app} reserves
udp.dstport in [53, 5353]
  go to UDP port 53 or 5353 | have UDP destination port 53 or 5353
  -
udp.dstport lt 5353
  go to a UDP port below 5353 | have a UDP destination port under 5353
  port: go to a UDP port below the one {app} reserves
udp.dstport ne 53
  are UDP datagrams not sent to port 53 | use a UDP destination port besides 53
  -
udp.srcport eq 53
  come from UDP port 53 | have UDP source port 53
  port: come from the UDP port {app} answers on
udp.srcport ne 53
  are UDP datagrams not sent from port 53 | use a UDP source port besides 53
  -
"""
HOSTS = (
    "the backup server",
    "the staging database",
    "the VPN gateway",
    "the build agent",
    "the lab camera",
)
APPS = (
    "the inventory service",
    "our metrics agent",
    "the license server",
    "the chat relay",
    "the sync daemon",
)
# One question per slot a non-ready variant can leave open.
QUESTIONS: dict[MissingSlot, str] = {
    MissingSlot.ADDRESS: "Which IP address or network does that host use?",
    MissingSlot.DIRECTION: "Which direction do you mean, source or "
    "destination?",
    MissingSlot.FIELD: "Which TCP flag do you mean?",
    MissingSlot.PORT: "Which port number do you mean?",
    MissingSlot.PROTOCOL: "Which transport do you mean, TCP or UDP?",
    MissingSlot.VALUE: "What exact value should the filter compare against?",
}


@dataclass(frozen=True)
class Atom:
    """One predicate of the closed world and how a request words it.

    Attributes:
        predicate: The typed predicate.
        wordings: Plural verb phrases that complete "packets that ...".
        slot: The slot a non-ready variant leaves open, if any.
        vague: The wording that leaves ``slot`` open.
    """

    predicate: Predicate
    wordings: tuple[str, str]
    slot: MissingSlot | None = None
    vague: str = ""


def _atom(header: str, wordings: str, vague: str) -> Atom:
    field, operator, *text = header.split(" ", 2)
    value: object = json.loads(text[0]) if text else None
    if isinstance(value, list):
        value = tuple(cast(list[ScalarValue], value))
    first, second = (wording.strip() for wording in wordings.split("|"))
    predicate = Predicate(
        field=field, operator=Operator(operator), value=cast(_Value, value)
    )
    if vague == "-":
        return Atom(predicate, (first, second))
    slot, phrase = vague.split(": ", 1)
    return Atom(predicate, (first, second), MissingSlot(slot), phrase)


def _parse(table: str) -> tuple[Atom, ...]:
    lines = [line.strip() for line in table.strip().splitlines()]
    return tuple(
        _atom(*lines[index : index + 3]) for index in range(0, len(lines), 3)
    )


ATOMS: tuple[Atom, ...] = _parse(_TABLE)
