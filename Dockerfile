FROM python:3.13-slim-bookworm


# Copy the uv binary from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /code


COPY ./pyproject.toml /code/pyproject.toml


RUN uv sync


COPY ./app /code/app

CMD ["uv", "run", "opentelemetry-instrument", "--service_name", "fastapi-hw", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]