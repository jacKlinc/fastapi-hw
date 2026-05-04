from datetime import datetime, timezone

from fastapi import FastAPI, status, HTTPException, Header, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select
from pygeohash import encode

from app.core.security import hash_password, verify_password
from app.db.session import get_db
from app.db.models import Users, Routes
from app.api.routes.auth import encrypt_payload, decrypt_payload

app = FastAPI()


@app.post("/auth/register")
def register(
    username: str, email: str, password: str, session: Session = Depends(get_db)
):
    """Create user in database"""
    hashed = hash_password(password)
    # TODO generate uuid
    new_user = Users(username=username, email=email, hashed_password=hashed)
    # TODO handle existing user
    session.add(new_user)
    session.commit()
    return {"Result": "Success!"}


@app.post("/auth/token")
def get_token(username: str, password: str, session: Session = Depends(get_db)):
    """Login to get valid token to make requests

    Raises:
        HTTPException: 404: User not found
        HTTPException: 401: User found, password failed
    """
    stmt = select(Users.hashed_password).where(Users.username == username)
    result = session.execute(stmt).scalars().first()

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if verify_password(password, result):
        response = {"status_code": 200}
        response["token"] = encrypt_payload({"user_id": username, "role": "admin"})
        return response

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Password failed"
    )


@app.get("/routes/{route_id}")
def get_route(
    route_id: int, token: str = Header(None), session: Session = Depends(get_db)
):
    """Returns specific route ID"""
    decrypt_payload(token)
    stmt = select(Routes).where(Routes.id == route_id)
    route = session.execute(stmt).scalar()
    if not route:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Route not found"
        )
    return route


@app.post("/routes")
def create_route(
    name: str,
    lat: float,
    lon: float,
    token: str = Header(None),
    session: Session = Depends(get_db),
):
    """Creates route"""
    decrypt_payload(token)
    route = Routes(
        name=name,
        lat=lat,
        lon=lon,
        geohash=encode(lat, lon),
        created_at=datetime.now(timezone.utc),
    )
    session.add(route)
    session.commit()
    return {"Result": "Success!"}


@app.get("/")
def read_root():
    return {"Hello": "World"}
