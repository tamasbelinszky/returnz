"""returnz-fastapi — FastAPI + Pydantic integration for returnz.

Return a ``Result`` from your services, then ``unwrap_or_raise`` at the route
boundary: ``Ok`` values flow through as the success type, ``Err`` values become
HTTP responses by the error's own status and tag (``HttpError``).
"""

from importlib.metadata import version

from returnz_fastapi.boundary import unwrap_or_raise
from returnz_fastapi.errors import HttpError
from returnz_fastapi.routing import BatchRoute, BatchRouter, ResultRoute, ResultRouter

__all__ = [
    "BatchRoute",
    "BatchRouter",
    "HttpError",
    "ResultRoute",
    "ResultRouter",
    "unwrap_or_raise",
]
__version__ = version("returnz-fastapi")
