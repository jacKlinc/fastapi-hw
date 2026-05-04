from sqlalchemy import text


def test_connect(client, db_engine):
    with db_engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        assert result.scalar() == 1
