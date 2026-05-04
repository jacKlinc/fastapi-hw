from os import getenv

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

load_dotenv(override=True)
user, password, port, database = (
    getenv("POSTGRES_USER"),
    getenv("POSTGRES_PASSWORD"),
    getenv("POSTGRES_PORT"),
    getenv("POSTGRES_DB"),
)
DATABASE_URL = f"postgresql://{user}:{password}@localhost:{port}/{database}"
engine = create_engine(DATABASE_URL)


def get_db():
    session = Session(engine)
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
