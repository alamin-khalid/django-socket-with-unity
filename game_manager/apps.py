from django.apps import AppConfig


class GameManagerConfig(AppConfig):
    name = 'game_manager'

    def ready(self):
        import os
        import sys
        
        # Only run on main process or runserver (avoid running on every management command check)
        # We check for 'runserver' in argv or RUN_MAIN (reloader)
        is_runserver = 'runserver' in sys.argv
        is_reloader = os.environ.get('RUN_MAIN') == 'true'
        
        if is_runserver or is_reloader:
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
