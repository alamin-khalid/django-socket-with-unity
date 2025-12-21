from django.apps import AppConfig


class GameManagerConfig(AppConfig):
    name = 'game_manager'

    def ready(self):
        import os
        import sys
        
        # Determine if we should start the scheduler
        # Option 1: Explicit environment variable (recommended for production)
        # Option 2: Detect runserver or daphne in argv
        # Option 3: Detect RUN_MAIN reloader
        scheduler_enabled = os.environ.get('SCHEDULER_ENABLED', '').lower() == 'true'
        is_runserver = 'runserver' in sys.argv
        is_daphne = any('daphne' in arg.lower() for arg in sys.argv)
        is_reloader = os.environ.get('RUN_MAIN') == 'true'
        
        should_start = scheduler_enabled or is_runserver or is_daphne or is_reloader
        
        print(f"[App Ready] scheduler_enabled={scheduler_enabled}, runserver={is_runserver}, daphne={is_daphne}, reloader={is_reloader}, should_start={should_start}")
        
        if should_start:
            try:
                from .startup import reset_all_servers_offline
                reset_all_servers_offline()
            except Exception as e:
                print(f"Error in startup cleanup: {e}")
            
            # Start background assignment scheduler (runs every second)
            try:
                from .scheduler import start_scheduler
                start_scheduler()
            except Exception as e:
                print(f"Error starting scheduler: {e}")
