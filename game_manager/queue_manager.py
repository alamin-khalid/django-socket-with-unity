import time
from django.conf import settings
import redis

# Connect to Redis directly for ZSET operations
# Using the same connection details as Channel Layer for simplicity
redis_client = redis.Redis(host='127.0.0.1', port=6379, db=0)

QUEUE_KEY = 'map_calculation_queue'

def add_to_queue(map_id, execute_at):
    """
    Adds a map to the calculation queue.
    execute_at: Timestamp (Unix epoch) when the map should be calculated.
    """
    # ZADD key score member
    redis_client.zadd(QUEUE_KEY, {str(map_id): execute_at})
    print(f"Added map {map_id} to queue for {execute_at}")

def get_due_tasks():
    """
    Returns a list of map_ids that are due for calculation (score <= now).
    """
    now = time.time()
    # ZRANGEBYSCORE key min max
    # Returns list of bytes, so we decode
    due_maps = redis_client.zrangebyscore(QUEUE_KEY, '-inf', now)
    return [m.decode('utf-8') for m in due_maps]

def pop_task(map_id):
    """
    Removes a map from the queue.
    """
    redis_client.zrem(QUEUE_KEY, str(map_id))

def get_queue_length():
    return redis_client.zcard(QUEUE_KEY)
