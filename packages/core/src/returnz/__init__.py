"""returnz — Result / Maybe / Reader for modern Python.

Concrete PEP 695 generics. No higher-kinded-type emulation, no type-checker
plugin. See the repository NOTICE for lineage (derived in spirit from
dry-python/returns).

Construct and match with the variant classes (``Ok`` / ``Err`` / ``Some`` /
``Nothing``) — each is a subtype of its union, just like Rust. Result operations
are exported here; Maybe operations live in ``returnz.maybe`` (their names would
otherwise collide with the Result ones).
"""

from returnz.batch import BatchResult, collect, gather_results, map_batch, partition
from returnz.do import do, do_async, require
from returnz.maybe import Maybe, Nothing, Some, ok_or
from returnz.reader import Reader
from returnz.result import (
    Err,
    Ok,
    Result,
    UnwrapError,
    and_then,
    map_err,
    map_ok,
    unwrap,
    unwrap_or,
)

__all__ = [
    "BatchResult",
    "Err",
    "Maybe",
    "Nothing",
    "Ok",
    "Reader",
    "Result",
    "Some",
    "UnwrapError",
    "and_then",
    "collect",
    "do",
    "do_async",
    "gather_results",
    "map_batch",
    "map_err",
    "map_ok",
    "ok_or",
    "partition",
    "require",
    "unwrap",
    "unwrap_or",
]
__version__ = "0.0.0"
