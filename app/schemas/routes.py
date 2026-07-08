from typing import Optional

from pydantic import BaseModel


class CreateRoute(BaseModel):
    name: str
    lat: float
    lon: float


class PaginationParams(BaseModel):
    offset: Optional[int] = None  # where the rows start
    limit: Optional[int] = None  # how many rows
    page: Optional[int] = None
    pageSize: Optional[int] = None
    since_id: Optional[int] = None


def pagination_params(
    offset: Optional[int] = None,
    limit: Optional[int] = 100,
    page: Optional[int] = None,
    pageSize: Optional[int] = None,
    since_id: Optional[int] = None,
) -> PaginationParams:
    return PaginationParams(
        offset=offset, limit=limit, page=page, pageSize=pageSize, since_id=since_id
    )
