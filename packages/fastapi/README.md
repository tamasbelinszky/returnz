# returnz-fastapi

FastAPI integration for [`returnz`](https://pypi.org/project/returnz/). Python 3.14+.

Return a `Result` from your services; `unwrap_or_raise` at the route boundary.
`Ok` values flow through as the success type; `Err` values become HTTP responses
by the error's own status and tag (`HttpError`). The boundary stays invisible to
the handler.

```python
from typing import Literal

from fastapi import FastAPI
from returnz import Ok, Err, Result, do_async, require
from returnz_fastapi import HttpError, unwrap_or_raise


class NotFound(HttpError):
    status_code = 404
    tag: Literal["not_found"] = "not_found"
    id: str


async def fetch_user(user_id: str) -> Result[User, NotFound]:
    user = await db.get(user_id)
    return Ok(user) if user is not None else Err(NotFound(id=user_id))


@do_async
async def zip_of(user_id: str) -> Result[str, NotFound]:
    user = require(await fetch_user(user_id))  # ? on the Result
    return Ok(user.zip)


app = FastAPI()


@app.get("/users/{user_id}/zip")
async def get_zip(user_id: str) -> str:
    return unwrap_or_raise(await zip_of(user_id))
```

- `GET /users/42/zip` → `200 "90210"`
- `GET /users/99/zip` → `404 {"detail": {"tag": "not_found", "id": "99"}}`
