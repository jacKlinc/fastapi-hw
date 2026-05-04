from pydantic import BaseModel


class CreateRoute(BaseModel):
    name: str
    lat: float
    lon: float
