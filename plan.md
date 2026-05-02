**Phase 1 — Foundation**

1. Set up project with `uv`, install FastAPI, SQLAlchemy async, asyncpg, uvicorn, python-jose, passlib, slowapi
2. Project structure as above — create all folders and empty files
3. PostgreSQL running via Docker Compose
4. DB session and connection working, basic users and routes tables
5. JWT auth end to end — `/auth/token` endpoint, password hashing, token generation and verification
6. One protected endpoint — `GET /routes` requiring a valid token

**Phase 2 — System design features**

1. Rate limiting via slowapi — anonymous vs authenticated limits
2. Async IO throughout — ensure all DB calls are properly async
3. Request timing middleware — `X-Response-Time` header
4.  Background tasks — async audit logging on each request
5.  Structured JSON logging with request ID

**Phase 3 — Polish**

1.  `POST /routes` with Pydantic validation and proper error responses (400, 422)
2.  `GET /routes/{id}` with geohash proximity query pulling from your earlier work
3.  In-memory cache with TTL on the routes endpoint
4.  Swagger docs cleaned up with descriptions and example payloads
5.  README documenting the system design decisions and why each was made
