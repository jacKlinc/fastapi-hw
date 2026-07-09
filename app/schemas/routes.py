from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CreateRoute(BaseModel):
    name: str
    lat: float
    lon: float


class RouteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    lat: float
    lon: float
    geohash: str
    created_at: datetime


class PaginationParams(BaseModel):
    offset: Optional[int] = None  # where the rows start
    limit: Optional[int] = None  # how many rows
    page: Optional[int] = None
    pageSize: Optional[int] = None
    since_id: Optional[int] = None
    cursor: Optional[str] = None


def pagination_params(
    offset: Optional[int] = None,
    limit: Optional[int] = 100,
    page: Optional[int] = None,
    pageSize: Optional[int] = None,
    since_id: Optional[int] = None,
    cursor: Optional[str] = None,
) -> PaginationParams:
    return PaginationParams(
        offset=offset,
        limit=limit,
        page=page,
        pageSize=pageSize,
        since_id=since_id,
        cursor=cursor,
    )
