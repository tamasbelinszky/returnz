"""TaggedError — base for serializable, matchable typed errors.

Subclass and set a ``Literal`` ``tag`` so a family of errors forms a
discriminated union that is both matchable in Python and serializable as data::

    class NotFound(TaggedError):
        tag: Literal["not_found"] = "not_found"
        id: str

    class RateLimited(TaggedError):
        tag: Literal["rate_limited"] = "rate_limited"
        retry_after: int

    type FetchError = Annotated[NotFound | RateLimited, Field(discriminator="tag")]

Used as the ``E`` of a ``Result`` (via ``RzResult``), such an error serializes
to ``{"err": {"tag": "not_found", "id": "…"}}`` and round-trips by tag.

The base intentionally declares no ``tag`` field: each subclass declares its own
``Literal`` tag, which is what a discriminated union needs and what keeps the
subclass a clean, matchable value (no mutable-field override to narrow).
"""

from pydantic import BaseModel


class TaggedError(BaseModel):
    model_config = {"frozen": True}
