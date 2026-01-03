"""
Game Manager - Redis Queue Operations
=====================================

This module provides a Redis-backed priority queue for scheduling planet calculations.
Redis Sorted Sets are used as the underlying data structure, enabling O(log N)
insertions and efficient time-based range queries.

Architecture
------------
    ┌─────────────────────────────────────────────────────────┐
    │                    Redis Server                          │
    │  ┌─────────────────────────────────────────────────────┐ │
    │  │  planet_round_queue (Sorted Set)                    │ │
    │  │                                                     │ │
    │  │  Member: planet_id   Score: next_round_time (unix)  │ │
    │  │  ─────────────────   ──────────────────────────────│ │
    │  │  "79001"             1703289600.0                   │ │
    │  │  "79002"             1703289660.0                   │ │
    │  │  "79003"             1703289720.0                   │ │
    │  └─────────────────────────────────────────────────────┘ │
    └─────────────────────────────────────────────────────────┘

Why Redis Sorted Sets?
----------------------
1. Time-based ordering: Score = Unix timestamp enables ZRANGEBYSCORE queries
2. O(log N) operations: Efficient for large planet counts
3. Atomic operations: No race conditions in concurrent access
4. Persistence options: Can survive Redis restarts (RDB/AOF)
5. Memory efficient: Sorted sets use ~64 bytes overhead per entry

Failure Mode
------------
All functions gracefully handle Redis unavailability:
- Return empty lists/None for read operations
- Return False for write operations
- Log warnings but don't crash the application
- The Django DB remains the source of truth; Redis is a scheduling cache

Configuration
-------------
Settings are read from Django settings with fallbacks:
- REDIS_HOST: Default '127.0.0.1'
- REDIS_PORT: Default 6379
- REDIS_DB: Default 0

Author: AL AMIN KHALID
Last Modified: 2024-12
"""

import redis
from redis.exceptions import RedisError, ConnectionError
from django.conf import settings
from datetime import datetime
from typing import List, Tuple, Optional


# =============================================================================
# CONFIGURATION
# =============================================================================

# Redis connection settings with sensible defaults for local development
REDIS_HOST: str = getattr(settings, 'REDIS_HOST', '127.0.0.1')
REDIS_PORT: int = getattr(settings, 'REDIS_PORT', 6379)
REDIS_DB: int = getattr(settings, 'REDIS_DB', 0)

# Queue key in Redis - all planet scheduling data lives here
QUEUE_KEY: str = 'planet_round_queue'


# =============================================================================
# CONNECTION MANAGEMENT
# =============================================================================

def _get_redis_client() -> Optional[redis.Redis]:
    """
    Create and validate a Redis client connection.
    
    Creates a new Redis client with short timeouts to prevent blocking
    the application if Redis is unavailable. Validates connection with
    a PING command before returning.
    
    Returns:
        redis.Redis: Connected client instance
        None: If connection failed
    
    Connection Settings:
        - decode_responses=True: Return strings instead of bytes
        - socket_connect_timeout=2s: Fail fast on connection issues
        - socket_timeout=2s: Fail fast on command timeout
    
    Note:
        This creates a new connection each call. For high-throughput
        scenarios, consider using a connection pool.
    """
    try:
        client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,  # Return str instead of bytes
            socket_connect_timeout=2,  # Fail fast
            socket_timeout=2
        )
        # Validate connection before returning
        client.ping()
        return client
    except (RedisError, ConnectionError) as e:
        return None


# =============================================================================
# QUEUE OPERATIONS
# =============================================================================

def add_planet_to_queue(planet_id: str, next_round_time: datetime) -> bool:
    """
    Add or update a planet in the scheduling queue.
    
    Uses Redis ZADD which is an upsert operation - if the planet already
    exists, its score (scheduled time) is updated. If not, it's inserted.
    
    Args:
        planet_id: Unique planet identifier (e.g., "79001")
        next_round_time: When the planet should be processed
    
    Returns:
        bool: True if successfully queued, False on Redis error
    
    Redis Command:
        ZADD planet_round_queue <unix_timestamp> <planet_id>
    
    Time Complexity: O(log N) where N is queue size
    
    Example:
        >>> add_planet_to_queue("79001", datetime(2024, 12, 23, 10, 0, 0))
        True  # Planet 79001 scheduled for 10:00 AM
    """
    try:
        client = _get_redis_client()
        if not client:
            return False

        # Convert datetime to Unix timestamp for Redis score
        score = next_round_time.timestamp()
        client.zadd(QUEUE_KEY, {planet_id: score})
        
        return True
        
    except RedisError as e:
        return False


def get_due_planets(limit: int = 10) -> List[str]:
    """
    Retrieve planets whose scheduled time has passed.
    
    Queries the sorted set for all planets with score <= current time.
    This is the primary query used by the scheduler to find work.
    
    Args:
        limit: Maximum number of planet IDs to return (default 10)
    
    Returns:
        List[str]: Planet IDs ready for processing, oldest first
        Empty list on Redis error or if no planets are due
    
    Redis Command:
        ZRANGEBYSCORE planet_round_queue 0 <now> LIMIT 0 <limit>
    
    Time Complexity: O(log N + M) where N is queue size, M is result size
    
    Why limit parameter?
        Prevents overwhelming the system with too many assignments at once.
        The scheduler runs every 5 seconds, so limiting to 10-20 planets
        per cycle provides smooth throughput.
    """
    try:
        client = _get_redis_client()
        if not client:
            return []

        from django.utils import timezone
        now = timezone.now().timestamp()
        
        # Query for planets where score (next_round_time) <= now
        # Score range: 0 to now (any past time including epoch)
        planet_ids = client.zrangebyscore(
            QUEUE_KEY,
            min=0,
            max=now,
            start=0,
            num=limit
        )
        
        # Ensure all IDs are strings (handle legacy bytes if decode_responses failed)
        return [
            pid if isinstance(pid, str) else pid.decode('utf-8')
            for pid in planet_ids
        ]
        
    except RedisError as e:
        return []


def remove_from_queue(planet_id: str) -> bool:
    """
    Remove a planet from the scheduling queue.
    
    Called when:
    - Planet is assigned to a server (prevent double-assignment)
    - Planet is deleted from database (signal handler cleanup)
    - Manual admin intervention
    
    Args:
        planet_id: Planet to remove from queue
    
    Returns:
        bool: True if removed (or didn't exist), False on Redis error
    
    Redis Command:
        ZREM planet_round_queue <planet_id>
    
    Time Complexity: O(log N)
    
    Note:
        ZREM is idempotent - removing a non-existent member is not an error.
    """
    try:
        client = _get_redis_client()
        if not client:
            return False

        client.zrem(QUEUE_KEY, planet_id)
        return True
        
    except RedisError as e:
        return False


# =============================================================================
# MONITORING / INSPECTION
# =============================================================================

def get_queue_size() -> int:
    """
    Get the total number of planets in the queue.
    
    Used by the dashboard to display queue statistics.
    
    Returns:
        int: Number of planets queued, 0 on Redis error
    
    Redis Command:
        ZCARD planet_round_queue
    
    Time Complexity: O(1)
    """
    try:
        client = _get_redis_client()
        if not client:
            return 0
        return client.zcard(QUEUE_KEY)
    except RedisError as e:
        return 0


def peek_next_due_time() -> Optional[datetime]:
    """
    Get the scheduled time of the next planet without removing it.
    
    Useful for:
    - Dashboard display ("Next planet in X seconds")
    - Scheduler optimization (sleep until next due time)
    
    Returns:
        datetime: When the next planet is due
        None: If queue is empty or Redis unavailable
    
    Redis Command:
        ZRANGE planet_round_queue 0 0 WITHSCORES
    
    Time Complexity: O(1) - just the first element
    """
    try:
        client = _get_redis_client()
        if not client:
            return None

        # Get first element (lowest score = soonest due)
        result = client.zrange(QUEUE_KEY, 0, 0, withscores=True)
        
        if result:
            # result = [('planet_id', score)]
            score = float(result[0][1])
            return datetime.fromtimestamp(score)
        return None
        
    except RedisError as e:
        return None


def get_all_queued_planets() -> List[Tuple[str, datetime]]:
    """
    Get all planets in queue with their scheduled times.
    
    Primarily for admin/debugging purposes. Not recommended for
    production queries on very large queues.
    
    Returns:
        List[Tuple[str, datetime]]: [(planet_id, scheduled_time), ...]
        Ordered by scheduled time (soonest first)
    
    Redis Command:
        ZRANGE planet_round_queue 0 -1 WITHSCORES
    
    Time Complexity: O(N) where N is queue size
    
    Warning:
        For large queues (10000+ planets), this could be slow.
        Use get_due_planets() with pagination for production.
    """
    try:
        client = _get_redis_client()
        if not client:
            return []

        # Get all members with scores
        results = client.zrange(QUEUE_KEY, 0, -1, withscores=True)
        
        return [
            (planet_id, datetime.fromtimestamp(float(score)))
            for planet_id, score in results
        ]
        
    except RedisError as e:
        return []
