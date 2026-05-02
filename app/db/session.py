from sqlalchemy import create_engine


# Database URL Format: postgresql://USER:PASSWORD@HOST:PORT/DB_NAME
DATABASE_URL = "postgresql://myuser:mypassword@localhost:5433/mydatabase"

engine = create_engine(DATABASE_URL)

# Test connection
with engine.connect() as conn:
    print("Successfully connected to PostgreSQL!")
