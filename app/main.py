import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.api.routes import auth, routes
from app.core.logging import setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Starting up")
    yield
    logger.info("Shutting down")


app = FastAPI(lifespan=lifespan)
app.include_router(routes.router)
app.include_router(auth.router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s %s %.1fms",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.get("/")
def read_root():
    return {"Hello": "World"}
