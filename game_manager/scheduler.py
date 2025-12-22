"""
Background Assignment Scheduler
Runs automatically when Django starts and checks queue every second.
"""
import threading
import time
import logging

logger = logging.getLogger(__name__)

_scheduler_running = False
_scheduler_thread = None


def assignment_loop():
    """
    Background loop that checks and assigns planets every 2 seconds.
    """
    global _scheduler_running
    logger.info("[Scheduler] ✅ Background assignment scheduler started")
    
    while _scheduler_running:
        try:
            from .assignment_service import assign_available_planets
            result = assign_available_planets()
            # Only log when something was actually assigned
            if result and "Assigned" in str(result) and "0" not in str(result):
                logger.info(f"[Scheduler] {result}")
        except Exception as e:
            logger.error(f"[Scheduler] Error: {e}", exc_info=True)
        
        time.sleep(2)  # Check every 2 seconds
    
    logger.info("[Scheduler] Background assignment scheduler stopped")


def start_scheduler():
    """
    Start the background assignment scheduler thread.
    """
    global _scheduler_running, _scheduler_thread
    
    if _scheduler_running:
        return  # Already running
    
    _scheduler_running = True
    _scheduler_thread = threading.Thread(target=assignment_loop, daemon=True)
    _scheduler_thread.start()
    print("[Scheduler] ✅ Background assignment scheduler started (checks every 1 second)")


def stop_scheduler():
    """
    Stop the background assignment scheduler.
    """
    global _scheduler_running
    _scheduler_running = False
    print("[Scheduler] Background assignment scheduler stopped")
