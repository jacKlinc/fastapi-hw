from datetime import datetime

from sqlalchemy import Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import String, Float, DateTime


class Base(DeclarativeBase):
    pass


class Routes(Base):
    __tablename__ = "routes"
    __table_args__ = (Index("ix_routes_lat_lon", "lat", "lon"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    geohash: Mapped[str] = mapped_column(String(12))  # 12 is geohash max len
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Users(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(default=datetime.now())
