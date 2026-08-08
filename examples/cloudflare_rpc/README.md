# returnz across a structured-clone / RPC boundary

Cloudflare Workers RPC — and the [structured clone algorithm](https://developer.mozilla.org/en-US/docs/Web/API/Web_Workers_API/Structured_clone_algorithm)
it builds on — **strips class identity**: a value crossing the boundary arrives as
plain data (no class, methods gone, `isinstance` false). So anything that must
cross has to be reconstructable from plain, self-describing data.

returnz is built for that: `Result` / `Maybe` / `BatchResult` are pure-data
variants that serialize to **tagged envelopes** and reconstruct **by tag**, never
by class identity. This PoC proves the round-trip.

```sh
uv run examples/cloudflare_rpc/poc.py
```

The "wire" is JSON bytes — a faithful stand-in for the structured-clone boundary
(JSON ⊂ the clone-safe types, and it definitively drops class identity). It
demonstrates:

- a **raw** returnz value can't cross (class identity isn't clone-safe) → you must serialize;
- serialize → wire → **reconstruct by tag** → a usable, matchable value;
- the `Err` channel is data too (typed errors survive);
- **`Some(None)` stays distinct from `Nothing`** (the null-ambiguity trap);
- a partial-success `BatchResult` crosses whole (successes + typed failures).

> **Note:** returnz can't yet *run* on Cloudflare Python Workers — Workers use
> Pyodide (Python 3.13) and returnz currently requires 3.14. This demonstrates the
> serialization *alignment*; the same tagged envelope would ride the real RPC wire
> once returnz supports 3.13. MCP tool results and any other JSON-RPC boundary work
> the same way.
