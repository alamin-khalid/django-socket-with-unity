# Django + Unity Server Orchestration

This project implements a system where multiple Unity Linux server builds connect to a Django backend over WebSockets for orchestration, monitoring, and command execution.

## Prerequisites

- Python 3.10+
- Redis (running on port 16379)
- Unity (for the client script)

## Setup

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Database Migrations:**
    ```bash
    python manage.py migrate
    ```

3.  **Run Redis:**
    Ensure Redis is running on port 16379.
    
    **Docker (Windows/Ubuntu):**
    ```bash
    docker run -d --name redis -p 16379:6379 --restart always redis:latest
    ```
    
    **Native Ubuntu:**
    ```bash
    # Edit /etc/redis/redis.conf and set: port 16379
    sudo systemctl restart redis
    ```

4.  **Run Django Server:**
    ```bash
    python manage.py runserver
    ```

5.  **Run Celery Worker:**
    ```bash
    celery -A server_orchestrator worker --loglevel=info
    ```

## Unity Client

1.  Copy `unity_scripts/UnityWebSocketClient.cs` to your Unity project.
2.  Ensure you have `Newtonsoft.Json` and `websocket-sharp` (or compatible) installed in Unity.
3.  Attach the script to a GameObject.
4.  Set `Backend Url` to `ws://localhost:8000/ws/server/`.
5.  Set `Server Id` to a unique ID for the server instance.

## Features

- **WebSocket Connection:** Unity servers connect to `ws://<host>/ws/server/<server_id>/`.
- **Command Sending:** Django can send commands (`start_game`, `stop_game`, etc.) to Unity.
- **Status Updates:** Unity sends periodic heartbeats with CPU and player count.
- **Celery Automation:** Background tasks for match allocation and health checks.
- **Dashboard:** Real-time server monitoring at `/dashboard/`.
- **Task History:** Full task history with search & pagination at `/task-history/`.

## API / Usage

- **Send Command (Python Shell):**
    ```python
    from game_manager.utils import send_command_to_server
    send_command_to_server('server01', 'start_game', {'matchId': 123})
    ```

- **Allocate Match (Celery):**
    ```python
    from game_manager.tasks import allocate_match_to_server
    allocate_match_to_server.delay(match_id)
    ```
