import json
from datetime import datetime

from fastapi import FastAPI, status, HTTPException, Response
from sqlalchemy.orm import Session
from sqlalchemy import select


from app.core.security import hash_password, verify_password
from app.db.session import engine
from app.db.models import Users, Routes
from app.api.routes.auth import encrypt_payload, decrypt_payload

app = FastAPI()

# TODO status codes


@app.post("/auth/register")
def register(username: str, email: str, password: str):
    hashed = hash_password(password)
    new_user = Users(username=username, email=email, hashed_password=hashed)
    with Session(engine) as session:
        session.add(new_user)
        session.commit()
    return {"Result": "Success!"}


@app.post("/auth/token")
def get_token(username: str, password: str):
    stmt = select(Users.hashed_password).where(Users.username == username)
    response = {}
    # Look up user by username and verify password
    with Session(engine) as session:
        result = session.execute(stmt).scalars().first()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
            )

        if verify_password(password, result):
            response["token"] = encrypt_payload({"user_id": username, "role": "admin"})
            response["status_code"] = 200
            return response

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Password failed"
    )


@app.get("/routes/{route_id}")
def get_route(username: str, password: str, route_id: int):
    response = get_token(username, password)
    if response["status_code"] == 200:
        token = decrypt_payload(response["token"])
        print(token)
        if datetime.fromtimestamp(token["exp"]) < datetime.now():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
            )
        stmt = select(Routes).where(Routes.id == route_id)
        with Session(engine) as session:
            route = session.execute(stmt).scalar()
            if not route:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Route not found"
                )
            return route


@app.get("/")
def read_root():
    return {"Hello": "World"}
