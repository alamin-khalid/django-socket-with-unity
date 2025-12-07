# Django + Unity Server Orchestration

This project implements a system where multiple Unity Linux server builds connect to a Django backend over WebSockets for orchestration, monitoring, and command execution.

## Prerequisites

- Python 3.10+
- Redis (running on default port 6379)
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
    Ensure Redis is running. On Windows, you might use WSL or a Docker container.

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
