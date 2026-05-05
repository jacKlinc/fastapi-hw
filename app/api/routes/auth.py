import logging

from fastapi import status, HTTPException, Depends, APIRouter
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.security import hash_password, verify_password, encrypt_payload
from app.db.session import get_db
from app.db.models import Users

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth")


@router.post("/register")
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
    logger.info("Registered user username=%s", username)
    return {"Result": "Success!"}


@router.post("/token")
def get_token(username: str, password: str, session: Session = Depends(get_db)):
    """Login to get valid token to make requests

    Raises:
        HTTPException: 404: User not found
        HTTPException: 401: User found, password failed
    """
    stmt = select(Users.hashed_password).where(Users.username == username)
    result = session.execute(stmt).scalars().first()

    if not result:
        logger.error("Login failed: user not found username=%s", username)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if verify_password(password, result):
        logger.info("Token issued username=%s", username)
        response = {"status_code": 200}
        response["token"] = encrypt_payload({"user_id": username, "role": "admin"})
        return response

    logger.error("Login failed: bad password username=%s", username)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Password failed"
    )
