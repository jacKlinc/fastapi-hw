from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict

import jwt

# TODO store in .env
KEY = "secret should be more than 32B just so you know"
ALGORITHM = "HS256"
# HS256 (symmetric) offers lower security with faster speeds
# RS256 (asymmetric) is safer because it requires private key for signing and public for verification


@dataclass
class Token:
    user_id: str
    role: str
    exp: int


def encrypt_payload(payload: Dict) -> str:
    payload["exp"] = datetime.now() + timedelta(days=30)
    return jwt.encode(payload, key=KEY, algorithm=ALGORITHM)


def decrypt_payload(encoded: str) -> Token:
    return jwt.decode(encoded, key=KEY, algorithms=[ALGORITHM])
