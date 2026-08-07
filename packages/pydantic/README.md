# returnz-pydantic

Pydantic v2 integration for [`returnz`](https://pypi.org/project/returnz/). Python 3.14+.

- **`RzResult[T, E]` / `RzMaybe[T]`** — use as Pydantic field types. They serialize
  as **tagged envelopes** (`{"ok": …}` / `{"err": …}` / `{"some": …}` /
  `{"nothing": true}`) and reconstruct by tag, so a value survives any boundary
  (JSON, structured clone, RPC). `Some(None)` stays distinct from `Nothing`.
  Keep using plain `Result` / `Maybe` everywhere else — the core stays Pydantic-free.
- **`parse(Model, data)` / `parse_json(Model, data)`** — validation as a boundary:
  `Result[Model, ValidationError]`.
- **`TaggedError`** — base for matchable, serializable typed errors.
