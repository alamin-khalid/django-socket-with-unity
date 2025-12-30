from django.apps import AppConfig


class GameManagerConfig(AppConfig):
    """
    Django app configuration for game_manager.
    
    Startup Behavior:
        On Django startup (runserver/daphne), runs reset_all_servers_offline()
        to ensure clean state after process restart.
    
    Scheduling:
        Job scheduling is handled by Celery Beat (see settings.py).
        The `process_due_planets` task runs every 5 seconds.
        
        To run Celery in production:
            celery -A server_orchestrator worker --beat --loglevel=info
    """
    name = 'game_manager'

    def ready(self):
        import os
        import sys
        
        # Detect if this is a web server process
        # (not migrations, shell, or other management commands)
        is_runserver = 'runserver' in sys.argv
        is_daphne = any('daphne' in arg.lower() for arg in sys.argv)
        is_reloader = os.environ.get('RUN_MAIN') == 'true'
        
        should_run_startup = is_runserver or is_daphne or is_reloader
        
        if should_run_startup:
            try:
                from .startup import reset_all_servers_offline
                reset_all_servers_offline()
                print("[App Ready] ✅ Startup cleanup complete")
            except Exception as e:
                print(f"[App Ready] ❌ Error in startup cleanup: {e}")
