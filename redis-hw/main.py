import redis

redis_client = redis.Redis("localhost", port=6379, decode_responses=True)

redis_client.set("my-key", "wow")

key = redis_client.get("my-key")
print(key)
