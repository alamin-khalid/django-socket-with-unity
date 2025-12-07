import redis
from django.conf import settings
from datetime import datetime

# Redis client for queue operations
redis_client = redis.Redis(host='127.0.0.1', port=6379, db=0, decode_responses=True)
QUEUE_KEY = 'map_round_queue'

def add_map_to_queue(map_id: str, next_round_time: datetime):
    """
    Add map to time-sorted queue.
    
    Args:
        map_id: Unique map identifier
        next_round_time: DateTime when the map should be processed
        
    The score is the Unix timestamp, allowing efficient time-based queries.
    """
    score = next_round_time.timestamp()
    redis_client.zadd(QUEUE_KEY, {map_id: score})
    print(f"[Queue] Added map {map_id} to queue for {next_round_time}")

def get_due_maps(limit: int = 10):
    """
    Get maps where next_round_time <= now.
    
    Args:
        limit: Maximum number of maps to return
        
    Returns:
        List of map_ids that are ready for processing
    """
    now = datetime.now().timestamp()
    # ZRANGEBYSCORE returns maps with score between 0 and now
    return redis_client.zrangebyscore(QUEUE_KEY, 0, now, start=0, num=limit)

def remove_from_queue(map_id: str):
    """
    Remove map from queue (when processing starts).
    
    Args:
        map_id: Map identifier to remove
    """
    redis_client.zrem(QUEUE_KEY, map_id)
    print(f"[Queue] Removed map {map_id} from queue")

def get_queue_size():
    """
    Get total number of maps in queue.
    
    Returns:
        Integer count of queued maps
    """
    return redis_client.zcard(QUEUE_KEY)

def peek_next_due_time():
    """
    Get timestamp of next due map without removing it.
    
    Returns:
        DateTime of next scheduled map, or None if queue is empty
    """
    result = redis_client.zrange(QUEUE_KEY, 0, 0, withscores=True)
    if result:
        return datetime.fromtimestamp(float(result[0][1]))
    return None

def get_all_queued_maps():
    """
    Get all maps in queue with their scheduled times.
    
    Returns:
        List of tuples: [(map_id, datetime), ...]
    """
    results = redis_client.zrange(QUEUE_KEY, 0, -1, withscores=True)
    return [(map_id, datetime.fromtimestamp(float(score))) for map_id, score in results]
