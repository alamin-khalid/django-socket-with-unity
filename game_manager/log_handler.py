"""
Redis-backed Logging Handler
=============================

Custom Python logging handler that stores log records in a Redis circular buffer.
Used to display system logs on the dashboard without database overhead.

Architecture:
    Logger -> RedisLogHandler -> Redis List (LPUSH + LTRIM)
                                      |
                            Dashboard View reads via get_recent_logs()

Buffer Characteristics:
    - Max 1000 entries (configurable)
    - FIFO order (newest first)
    - Automatic trimming on insert
    - JSON serialized entries

Author: AL AMIN KHALID
Last Modified: 2026-01
"""

import logging
import json
import redis
from datetime import datetime
from typing import List, Dict, Optional
from django.conf import settings


# Configuration
REDIS_HOST = getattr(settings, 'REDIS_HOST', '127.0.0.1')
REDIS_PORT = getattr(settings, 'REDIS_PORT', 6379)
REDIS_DB = getattr(settings, 'REDIS_DB', 0)
LOG_KEY = 'system_logs'
MAX_LOG_ENTRIES = 1000


def _get_redis_client() -> Optional[redis.Redis]:
    """Get Redis client with error handling."""
    try:
        client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2
        )
        client.ping()
        return client
    except Exception:
        return None


class RedisLogHandler(logging.Handler):
    """
    Logging handler that stores records in Redis circular buffer.
    
    Each log entry is stored as JSON with:
    - timestamp: ISO format datetime
    - level: DEBUG, INFO, WARNING, ERROR, CRITICAL
    - logger: Logger name (e.g., 'game_manager.tasks')
    - message: Formatted log message
    
    Usage:
        Configured in Django settings.py LOGGING dict.
        Records are automatically pushed to Redis on emit().
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.redis_client = None
    
    def _ensure_connection(self) -> Optional[redis.Redis]:
        """Lazy connection to Redis."""
        if self.redis_client is None:
            self.redis_client = _get_redis_client()
        return self.redis_client
    
    def emit(self, record: logging.LogRecord) -> None:
        """
        Store log record in Redis.
        
        Fails silently if Redis is unavailable to avoid
        disrupting the main application.
        """
        try:
            client = self._ensure_connection()
            if not client:
                return
            
            # Format the log entry
            log_entry = {
                'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                'level': record.levelname,
                'logger': record.name,
                'message': self.format(record) if self.formatter else record.getMessage()
            }
            
            # Push to front of list and trim to max size
            client.lpush(LOG_KEY, json.dumps(log_entry))
            client.ltrim(LOG_KEY, 0, MAX_LOG_ENTRIES - 1)
            
        except Exception:
            # Never let logging errors crash the app
            pass


def get_recent_logs(limit: int = 100, level_filter: Optional[str] = None) -> List[Dict]:
    """
    Retrieve recent logs from Redis buffer.
    
    Args:
        limit: Maximum number of logs to return (default 100)
        level_filter: Optional level to filter by (e.g., 'ERROR')
    
    Returns:
        List of log entry dicts, newest first
    
    Example:
        >>> logs = get_recent_logs(limit=50, level_filter='WARNING')
        >>> for log in logs:
        ...     print(f"[{log['level']}] {log['message']}")
    """
    try:
        client = _get_redis_client()
        if not client:
            return []
        
        # Fetch more than limit if filtering (to ensure enough results after filter)
        fetch_count = limit * 3 if level_filter else limit
        raw_logs = client.lrange(LOG_KEY, 0, fetch_count - 1)
        
        logs = []
        for raw in raw_logs:
            try:
                entry = json.loads(raw)
                if level_filter and entry.get('level') != level_filter:
                    continue
                logs.append(entry)
                if len(logs) >= limit:
                    break
            except json.JSONDecodeError:
                continue
        
        return logs
        
    except Exception:
        return []


def clear_logs() -> bool:
    """
    Clear all logs from Redis buffer.
    
    Returns:
        True if successful, False otherwise
    """
    try:
        client = _get_redis_client()
        if client:
            client.delete(LOG_KEY)
            return True
        return False
    except Exception:
        return False
