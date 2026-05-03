from datetime import datetime, timedelta
from typing import Dict

import jwt

# TODO store in .env
KEY = "secret should be more than 32B just so you know"
ALGORITHM = "HS256"
# HS256 (symmetric) offers lower security with faster speeds
# RS256 (asymmetric) is safer because it requires private key for signing and public for verification


def encrypt_payload(payload: Dict) -> str:
    payload["exp"] = datetime.now() + timedelta(minutes=30)
    return jwt.encode(payload, key=KEY, algorithm=ALGORITHM)


def decrypt_payload(encoded: str) -> dict:
    return jwt.decode(encoded, key=KEY, algorithms=[ALGORITHM])
