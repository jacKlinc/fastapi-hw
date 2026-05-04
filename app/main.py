from fastapi import FastAPI, status, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import select


from app.core.security import hash_password, verify_password
from app.db.session import engine
from app.db.models import Users, Routes
from app.api.routes.auth import encrypt_payload, decrypt_payload

app = FastAPI()


@app.post("/auth/register")
def register(username: str, email: str, password: str):
    """Create user in database"""
    hashed = hash_password(password)
    new_user = Users(username=username, email=email, hashed_password=hashed)
    with Session(engine) as session:
        session.add(new_user)
        session.commit()
    return {"Result": "Success!"}


@app.post("/auth/token")
def get_token(username: str, password: str):
    """Login to get valid token to make requests

    Raises:
        HTTPException: 404: User not found
        HTTPException: 401: User found, password failed
    """
    stmt = select(Users.hashed_password).where(Users.username == username)
    with Session(engine) as session:
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
def get_route(route_id: int, token: str = Header(None)):
    """Returns specific route ID"""
    decrypt_payload(token)
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
