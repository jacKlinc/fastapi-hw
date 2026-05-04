from app.db.session import get_db


def test_connect():
    assert get_db() is not None
