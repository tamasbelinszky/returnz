"""Tests for Reader — environment-threading DI."""

from returnz import Reader


class TestRun:
    def test_supplies_environment(self) -> None:
        reader: Reader[int, int] = Reader(lambda env: env + 1)

        actual = reader.run(2)

        assert actual == 3


class TestMap:
    def test_maps_result_after_running(self) -> None:
        reader: Reader[int, int] = Reader(lambda env: env + 1)

        mapped = reader.map(lambda a: a * 10)

        assert mapped.run(2) == 30


class TestAndThen:
    def test_threads_the_same_environment(self) -> None:
        reader: Reader[int, int] = Reader(lambda env: env + 1)

        chained = reader.and_then(lambda a: Reader[int, int](lambda env: a * env))

        assert chained.run(3) == 12
