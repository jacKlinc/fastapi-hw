from fastapi import FastAPI
from sqlalchemy.orm import Session
from sqlalchemy import select


from app.core.security import hash_password, verify_password
from app.db.session import engine
from app.db.models import Users, Routes

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
    # Look up user by username and verify password
    with Session(engine) as session:
        result = session.execute(stmt).scalars().first()

        if not result:
            return 401

        if verify_password(password, result):
            return {"Result": "Success!"}

    return {"Result": "Failure!"}


@app.get("/")
def read_root():
    return {"Hello": "World"}
