# FastAPI Routes API

A REST API for managing geographic routes. Users register, authenticate via JWT, and create or retrieve routes stored with lat/lon coordinates and a geohash.

## File Structure
```
app/
  api/
    routes/
      auth.py       # register + token endpoints
      routes.py     # CRUD route endpoints
  core/
    config.py       # pydantic-settings config from .env
    logging.py      # logging dictConfig setup
    security.py     # JWT encrypt/decrypt, password hashing
  db/
    models.py
    session.py
  main.py           # app factory, lifespan, middleware
```

## Running

```bash
# Start Postgres
docker compose up -d

# Run API (hot reload)
uv run uvicorn app.main:app --reload
```

Connect to the DB directly:
```bash
docker exec -it fastapi-hw-db-1 psql -U myuser -d mydatabase
```

## Logging

Logging is configured in `app/core/logging.py` using Python's `logging.dictConfig` and initialised via FastAPI's `lifespan` hook.

**FastAPI-specific patterns used:**

- **`lifespan` for setup/teardown** — logging is configured in the `lifespan` async context manager rather than at module import time, so it runs after uvicorn's own loggers are initialised. This avoids a race where `dictConfig` resets uvicorn's handlers.

- **`disable_existing_loggers: False`** — the dictConfig keeps uvicorn's built-in `uvicorn` and `uvicorn.access` loggers intact. Overriding these breaks uvicorn's startup banner and access log format.

- **`logging.getLogger(__name__)` per module** — each router file gets its own logger (`app.api.routes.routes`, `app.api.routes.auth`) so log output is traceable to its source without extra fields.
