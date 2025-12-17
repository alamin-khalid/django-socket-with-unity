import redis
from redis.exceptions import RedisError, ConnectionError
from django.conf import settings
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Redis configuration from settings (with fallback defaults)
REDIS_HOST = getattr(settings, 'REDIS_HOST', '127.0.0.1')
REDIS_PORT = getattr(settings, 'REDIS_PORT', 6379)
REDIS_DB = getattr(settings, 'REDIS_DB', 0)
QUEUE_KEY = 'map_round_queue'

def _get_redis_client():
    """
    Get Redis client with connection validation.
    Returns None if Redis is unavailable.
    """
    try:
        client = redis.Redis(
            host=REDIS_HOST, 
            port=REDIS_PORT, 
            db=REDIS_DB, 
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2
        )
        # Test connection
        client.ping()
        return client
    except (RedisError, ConnectionError) as e:
        logger.error(f"Redis connection failed: {e}")
        return None

def add_map_to_queue(map_id: str, next_round_time: datetime):
    """
    Add map to time-sorted queue.
    
    Args:
        map_id: Unique map identifier
        next_round_time: DateTime when the map should be processed
        
    The score is the Unix timestamp, allowing efficient time-based queries.
    """
    try:
        client = _get_redis_client()
        if not client:
            logger.warning(f"Queue unavailable, map {map_id} not queued to Redis (DB state unchanged)")
            return False
            
        score = next_round_time.timestamp()
        client.zadd(QUEUE_KEY, {map_id: score})
        logger.info(f"[Queue] Added map {map_id} to queue for {next_round_time}")
        return True
    except RedisError as e:
        logger.error(f"Failed to queue map {map_id}: {e}")
        return False

def get_due_maps(limit: int = 10):
    """
    Get maps where next_round_time <= now.
    
    Args:
        limit: Maximum number of maps to return
        
    Returns:
        List of map_ids that are ready for processing
    """
    try:
        client = _get_redis_client()
        if not client:
            return []
            
        from django.utils import timezone
        now = timezone.now().timestamp()
        # ZRANGEBYSCORE returns maps with score between 0 and now
        map_ids = client.zrangebyscore(QUEUE_KEY, 0, now, start=0, num=limit)
        return [map_id if isinstance(map_id, str) else map_id.decode('utf-8') for map_id in map_ids]
    except RedisError as e:
        logger.error(f"Failed to get due maps: {e}")
        return []

def remove_from_queue(map_id: str):
    """
    Remove map from queue (when processing starts).
    
    Args:
        map_id: Map identifier to remove
    """
    try:
        client = _get_redis_client()
        if not client:
            logger.warning(f"Queue unavailable, could not remove map {map_id}")
            return False
            
        client.zrem(QUEUE_KEY, map_id)
        logger.info(f"[Queue] Removed map {map_id} from queue")
        return True
    except RedisError as e:
        logger.error(f"Failed to remove map {map_id} from queue: {e}")
        return False

def get_queue_size():
    """
    Get total number of maps in queue.
    
    Returns:
        Integer count of queued maps, or 0 if Redis unavailable
    """
    try:
        client = _get_redis_client()
        if not client:
            return 0
        return client.zcard(QUEUE_KEY)
    except RedisError as e:
        logger.error(f"Failed to get queue size: {e}")
        return 0

def peek_next_due_time():
    """
    Get timestamp of next due map without removing it.
    
    Returns:
        DateTime of next scheduled map, or None if queue is empty
    """
    try:
        client = _get_redis_client()
        if not client:
            return None
            
        result = client.zrange(QUEUE_KEY, 0, 0, withscores=True)
        if result:
            return datetime.fromtimestamp(float(result[0][1]))
        return None
    except RedisError as e:
        logger.error(f"Failed to peek next due time: {e}")
        return None

def get_all_queued_maps():
    """
    Get all maps in queue with their scheduled times.
    
    Returns:
        List of tuples: [(map_id, datetime), ...]
    """
    try:
        client = _get_redis_client()
        if not client:
            return []
            
        results = client.zrange(QUEUE_KEY, 0, -1, withscores=True)
        return [(map_id, datetime.fromtimestamp(float(score))) for map_id, score in results]
    except RedisError as e:
        logger.error(f"Failed to get all queued maps: {e}")
        return []
