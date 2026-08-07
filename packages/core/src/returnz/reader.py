"""Reader[Env, A] — a computation awaiting an environment.

A thin wrapper over ``Env -> A`` for dependency injection outside request
handlers (inside FastAPI, use ``Depends``). Deliberately minimal: no IO/Future
tower. Call ``reader.run(env)`` to supply the environment.
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Reader[Env, A]:
    run: Callable[[Env], A]

    def map[B](self, f: Callable[[A], B]) -> Reader[Env, B]:
        run = self.run
        return Reader(lambda env: f(run(env)))

    def and_then[B](self, f: Callable[[A], Reader[Env, B]]) -> Reader[Env, B]:
        run = self.run
        return Reader(lambda env: f(run(env)).run(env))
