import redis

redis_client = redis.Redis("localhost", port=6379, decode_responses=True)

redis_client.set("my-key", "wow")
redis_client.geoadd("bikes:rentable", [-122.27652, 37.805186, "station:1"])
redis_client.geoadd("bikes:rentable", [-122.274, 37.82, "station:2"])

key = redis_client.get("my-key")
print(key)

# https://redis.io/docs/latest/develop/data-types/geospatial/
# https://youtu.be/qftiVQraxmI
res4 = redis_client.geosearch(
    "bikes:rentable",
    longitude=-122.27652,
    latitude=37.805186,
    radius=5,
    unit="km",
    sort="DESC",
    count=1,
)
print(res4)
