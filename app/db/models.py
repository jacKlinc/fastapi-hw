from datetime import datetime

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import String, Float, DateTime


class Base(DeclarativeBase):
    pass


class Routes(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    geohash: Mapped[str] = mapped_column(String(12))  # 12 is geohash max len
    created_at: Mapped[datetime] = mapped_column(DateTime)
