"""returnz-fastapi — FastAPI + Pydantic integration for returnz.

Maps ``Err`` values onto HTTP responses (``Err -> HTTPException`` by error tag),
lets ``Result`` / ``Maybe`` cross the wire as tagged JSON, and wires validated
Pydantic settings as dependencies.
"""

__all__: list[str] = []
__version__ = "0.0.0"
