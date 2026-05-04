from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict

import jwt
import bcrypt

from app.core.config import settings

KEY = settings.jwt_secret
ALGORITHM = settings.jwt_algorithm


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


@dataclass
class Token:
    user_id: str
    role: str
    exp: int


def encrypt_payload(payload: Dict) -> str:
    payload["exp"] = datetime.now() + timedelta(
        days=30  # TODO change to something sensible
    )
    return jwt.encode(payload, key=KEY, algorithm=ALGORITHM)


def decrypt_payload(encoded: str) -> Token:
    return jwt.decode(encoded, key=KEY, algorithms=[ALGORITHM])
