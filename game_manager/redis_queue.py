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
QUEUE_KEY = 'planet_round_queue'

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

def add_planet_to_queue(planet_id: str, next_round_time: datetime):
    """
    Add planet to time-sorted queue.
    
    Args:
        planet_id: Unique planet identifier
        next_round_time: DateTime when the planet should be processed
        
    The score is the Unix timestamp, allowing efficient time-based queries.
    """
    try:
        client = _get_redis_client()
        if not client:
            logger.warning(f"Queue unavailable, planet {planet_id} not queued to Redis (DB state unchanged)")
            return False
            
        score = next_round_time.timestamp()
        client.zadd(QUEUE_KEY, {planet_id: score})
        logger.info(f"[Queue] Added planet {planet_id} to queue for {next_round_time}")
        return True
    except RedisError as e:
        logger.error(f"Failed to queue planet {planet_id}: {e}")
        return False

def get_due_planets(limit: int = 10):
    """
    Get planets where next_round_time <= now.
    
    Args:
        limit: Maximum number of planets to return
        
    Returns:
        List of planet_ids that are ready for processing
    """
    try:
        client = _get_redis_client()
        if not client:
            return []
            
        from django.utils import timezone
        now = timezone.now().timestamp()
        # ZRANGEBYSCORE returns planets with score between 0 and now
        planet_ids = client.zrangebyscore(QUEUE_KEY, 0, now, start=0, num=limit)
        return [planet_id if isinstance(planet_id, str) else planet_id.decode('utf-8') for planet_id in planet_ids]
    except RedisError as e:
        logger.error(f"Failed to get due planets: {e}")
        return []

def remove_from_queue(planet_id: str):
    """
    Remove planet from queue (when processing starts).
    
    Args:
        planet_id: Planet identifier to remove
    """
    try:
        client = _get_redis_client()
        if not client:
            logger.warning(f"Queue unavailable, could not remove planet {planet_id}")
            return False
            
        client.zrem(QUEUE_KEY, planet_id)
        logger.info(f"[Queue] Removed planet {planet_id} from queue")
        return True
    except RedisError as e:
        logger.error(f"Failed to remove planet {planet_id} from queue: {e}")
        return False

def get_queue_size():
    """
    Get total number of planets in queue.
    
    Returns:
        Integer count of queued planets, or 0 if Redis unavailable
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
    Get timestamp of next due planet without removing it.
    
    Returns:
        DateTime of next scheduled planet, or None if queue is empty
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

def get_all_queued_planets():
    """
    Get all planets in queue with their scheduled times.
    
    Returns:
        List of tuples: [(planet_id, datetime), ...]
    """
    try:
        client = _get_redis_client()
        if not client:
            return []
            
        results = client.zrange(QUEUE_KEY, 0, -1, withscores=True)
        return [(planet_id, datetime.fromtimestamp(float(score))) for planet_id, score in results]
    except RedisError as e:
        logger.error(f"Failed to get all queued planets: {e}")
        return []
