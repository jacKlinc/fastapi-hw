
### File Structure
```bash
app/
  api/
    routes/
      auth.py
      routes.py
  core/
    config.py
    security.py
    rate_limit.py
  db/
    models.py
    session.py
  middleware/
    logging.py
    timing.py
  main.py
```

## Docker
1. Start container: `docker compose up -d`
2. Connect to DB: `docker exec -it fastapi-hw-db-1 psql -U myuser -d mydatabase`
3. `SELECT * FROM routes;`

