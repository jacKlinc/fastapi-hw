FROM python:3.13-slim-bookworm


# Copy the uv binary from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /code


COPY ./pyproject.toml /code/pyproject.toml


RUN uv sync


COPY ./app /code/app

# run: docker run --env-file .env -p 8000:8000 fast-api
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]