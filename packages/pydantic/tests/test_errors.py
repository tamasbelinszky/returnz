"""Tests for TaggedError — matchable, serializable, frozen typed errors."""

from typing import Literal

import pytest
from pydantic import ValidationError

from returnz_pydantic import TaggedError


class NotFound(TaggedError):
    tag: Literal["not_found"] = "not_found"
    id: str


class TestTaggedError:
    def test_matchable_by_keyword_pattern(self) -> None:
        error = NotFound(id="42")

        match error:
            case NotFound(id=found):
                actual = found
            case _:
                actual = "no-match"

        assert actual == "42"

    def test_serializes_with_tag(self) -> None:
        assert NotFound(id="42").model_dump() == {"tag": "not_found", "id": "42"}

    def test_is_frozen(self) -> None:
        error = NotFound(id="42")

        with pytest.raises(ValidationError, match="frozen"):
            # setattr (not `error.id = ...`) so this runtime-frozen check does not
            # trip the static read-only error that ty/pyright would raise.
            setattr(error, "id", "99")  # noqa: B010
