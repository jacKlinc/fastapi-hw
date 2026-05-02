import math
import random
from datetime import datetime, timezone

import pygeohash
from sqlalchemy.orm import Session

from app.db.models import Base, Routes
from app.db.session import engine

CANMORE_LAT = 51.0884
CANMORE_LON = -115.3479
RADIUS_KM = 50
COUNT = 100_000


def random_point_within_radius(center_lat: float, center_lon: float, radius_km: float) -> tuple[float, float]:
    # sqrt ensures uniform area distribution (not clumped at center)
    r = radius_km * math.sqrt(random.random())
    theta = random.uniform(0, 2 * math.pi)

    delta_lat = r / 111.0
    delta_lon = r / (111.0 * math.cos(math.radians(center_lat)))

    return center_lat + delta_lat * math.cos(theta), center_lon + delta_lon * math.sin(theta)


Base.metadata.create_all(engine)

print(f"Seeding {COUNT:,} routes...")
batch_size = 1000
now = datetime.now(timezone.utc)

with Session(engine) as session:
    for batch_start in range(0, COUNT, batch_size):
        batch = [
            Routes(
                name=f"Route {batch_start + i + 1}",
                lat=(pt := random_point_within_radius(CANMORE_LAT, CANMORE_LON, RADIUS_KM))[0],
                lon=pt[1],
                geohash=pygeohash.encode(pt[0], pt[1], precision=12),
                created_at=now,
            )
            for i in range(batch_size)
        ]
        session.bulk_save_objects(batch)
        session.commit()
        if (batch_start // batch_size + 1) % 10 == 0:
            print(f"  {batch_start + batch_size:,} / {COUNT:,}")

print("Done.")
