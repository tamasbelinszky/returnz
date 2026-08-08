# /// script
# requires-python = ">=3.14"
# dependencies = ["returnz-pydantic"]
# ///
"""PoC — returnz values survive a structured-clone / RPC boundary.

Cloudflare Workers RPC (and the structured clone algorithm it builds on) **strips
class identity**: an object crossing the boundary arrives as plain data — no
class/prototype, methods gone, ``isinstance`` false. So a value that must cross a
boundary has to be reconstructable from plain, self-describing data.

returnz is designed for exactly this: ``Result`` / ``Maybe`` / ``BatchResult`` are
pure-data variants that serialize to **tagged envelopes** and are reconstructed
**by tag** (never by class identity). This script proves the round-trip.

The "wire" here is JSON bytes — a faithful stand-in for the structured-clone
boundary: JSON is a subset of the clone-supported types, and it definitively drops
all class identity. On actual Cloudflare Python Workers the *same* tagged envelope
would ride the RPC wire unchanged (pending returnz supporting Pyodide's Python).

Run:  uv run examples/cloudflare_rpc/poc.py
"""

from typing import Any, Literal

from pydantic import BaseModel, TypeAdapter

from returnz import BatchResult, Err, Nothing, Ok, Result, Some
from returnz_pydantic import RzBatchResult, RzMaybe, RzResult, TaggedError


class User(BaseModel):
    id: str
    name: str


class NotFound(TaggedError):
    tag: Literal["not_found"] = "not_found"
    id: str


# The boundary: only structured-clone-safe data crosses. A class instance loses
# its class (like a prototype-less object on the other side), so sending a raw
# returnz value naively is impossible — you must serialize to a tagged envelope.
_CLONE_SAFE = (str, int, float, bool, type(None), dict, list)


def crosses_boundary_raw(value: object) -> bool:
    return isinstance(value, _CLONE_SAFE)


_result = TypeAdapter(RzResult[User, NotFound])
_maybe = TypeAdapter(RzMaybe[int | None])
_batch = TypeAdapter(RzBatchResult[str, str, NotFound])


def line(label: str, ok: bool, detail: Any = "") -> None:
    print(f"  [{'ok' if ok else 'XX'}] {label:42} {detail}")


print("1. A raw returnz value cannot cross — class identity isn't clone-safe:")
raw = Ok(User(id="42", name="Ann"))
line(
    "isinstance(Ok(...), clone-safe types)",
    not crosses_boundary_raw(raw),
    "-> must serialize first",
)

print("\n2. Serialize -> cross the wire (bytes only) -> reconstruct BY TAG:")
wire = _result.dump_json(raw)  # what actually crosses
print(f"     wire = {wire.decode()}")
received = _result.validate_json(wire)  # far side has only bytes; rebuilds by the 'ok' tag
line("round-trips equal", received == raw)
match received:
    case Ok(user):
        line("reconstructed value is usable (matchable)", True, f"-> user.name = {user.name!r}")
    case Err(_):
        line("unexpected Err", False)

print("\n3. The Err channel is data too — typed error survives the wire:")
err_wire = _result.dump_json(Err(NotFound(id="99")))
print(f"     wire = {err_wire.decode()}")
line("Err(NotFound) round-trips", _result.validate_json(err_wire) == Err(NotFound(id="99")))

print("\n4. The null-ambiguity trap: Some(None) stays distinct from Nothing:")
sn, no = _maybe.dump_json(Some(None)), _maybe.dump_json(Nothing())
print(f"     Some(None) -> {sn.decode()}    Nothing() -> {no.decode()}")
line("distinct on the wire", sn != no)
line("Some(None) round-trips", _maybe.validate_json(sn) == Some(None))
line("Nothing round-trips", _maybe.validate_json(no) == Nothing())

print("\n5. Partial-success BatchResult crosses whole (successes + typed failures):")
outcome = BatchResult(succeeded={"1": "1"}, failed={"2": NotFound(id="2")})
batch_wire = _batch.dump_json(outcome)
print(f"     wire = {batch_wire.decode()}")
line("BatchResult round-trips", _batch.validate_json(batch_wire) == outcome)

print("\nAll returnz values crossed the structured-clone/RPC boundary by tag, not by class.")
