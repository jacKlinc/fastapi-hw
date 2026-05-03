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


@app.get("/")
def read_root():
    return {"Hello": "World"}
