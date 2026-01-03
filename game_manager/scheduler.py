"""
Background Assignment Scheduler
Runs automatically when Django starts and checks queue every second.
"""
import threading
import time


_scheduler_running = False
_scheduler_thread = None


def assignment_loop():
    """
    Background loop that checks and assigns planets every 2 seconds.
    """
    global _scheduler_running
    
    while _scheduler_running:
        try:
            from .assignment_service import assign_available_planets
            assign_available_planets()
        except Exception:
            pass
        
        time.sleep(2)  # Check every 2 seconds
    


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
    print("[Scheduler] ✅ Background assignment scheduler started (checks every 2 seconds)")


def stop_scheduler():
    """
    Stop the background assignment scheduler.
    """
    global _scheduler_running
    _scheduler_running = False
    print("[Scheduler] Background assignment scheduler stopped")
