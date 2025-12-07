# Django-Unity Server Orchestrator - Quick Start Guide

## 🚀 Quick Start (5 Minutes)

### 1. Install Dependencies (30 seconds)
```powershell
cd "d:\Krada Pyhton\django-socket-with-unity"
pip install -r requirements.txt
```

### 2. Setup Database (30 seconds)
```powershell
# Migrations already applied ✓
# If you need to reset:
# python manage.py migrate
```

### 3. Create Test Data (30 seconds)
```powershell
python manage.py shell < create_test_data.py
```

### 4. Start All Services (4 terminals)

**Terminal 1 - Redis**:
```powershell
redis-server
```

**Terminal 2 - Django**:
```powershell
cd "d:\Krada Pyhton\django-socket-with-unity"
python manage.py runserver
```

**Terminal 3 - Celery Worker**:
```powershell
cd "d:\Krada Pyhton\django-socket-with-unity"
celery -A server_orchestrator worker --loglevel=info --pool=solo
```

**Terminal 4 - Celery Beat**:
```powershell
cd "d:\Krada Pyhton\django-socket-with-unity"
celery -A server_orchestrator beat --loglevel=info
```

---

## 🎮 Unity Server Setup

1. **Add Script to Unity**:
   - Copy `unity_scripts/UnityWebSocketClient.cs` to your Unity project
   - Attach to a GameObject

2. **Configure**:
   ```csharp
   backendWsUrl = "ws://localhost:8000/ws/server/"
   backendApiUrl = "http://localhost:8000"
   serverId = "unity_01"  // Must be unique per server
   ```

3. **Build & Run**:
   - Build as headless Linux server or Windows executable
   - Run the executable

---

## 📊 Monitoring

### Check Queue Status
```powershell
curl http://localhost:8000/api/queue/
```

### List Active Servers
```powershell
curl http://localhost:8000/api/servers/
```

### View Redis Queue
```powershell
redis-cli
> ZCARD map_round_queue
> ZRANGE map_round_queue 0 -1 WITHSCORES
```

---

## 🧪 Test the System

### Check Logs

**Django** should show:
```
[WebSocket] Server unity_01 connected and registered as idle
```

**Celery Beat** should show (every 5s):
```
[INFO] Task game_manager.tasks.process_due_maps[...] succeeded
```

**Celery Worker** should show (when job assigned):
```
[INFO] Assigned map test_map_alpha to server unity_01
```

**Unity** should show:
```
[WebSocket] Connected to ws://localhost:8000/ws/server/unity_01/
[Job] Assigned: Map test_map_alpha, Round 0, Season 1
[Job] Processing map test_map_alpha
[API] Results submitted successfully
```

---

## ⚡ Key Endpoints

| Endpoint | Purpose |
|----------|---------|
| `ws://localhost:8000/ws/server/{server_id}/` | WebSocket connection |
| `GET /api/queue/` | Queue statistics |
| `GET /api/map/{map_id}/` | Fetch map configuration |
| `POST /api/result/` | Submit job results |
| `GET /api/servers/` | List all servers |

---

## 🐛 Troubleshooting

### "No module named 'channels_redis'"
```powershell
pip install channels-redis
```

### "ZCARD command failed"
```powershell
# Redis not running
redis-server
```

### "No servers available"
- Check Unity is connected: `curl http://localhost:8000/api/servers/`
- Check Unity logs for connection errors

### Unity "Connection refused"
- Ensure Django is running: `python manage.py runserver`
- Check WebSocket URL in Unity matches Django

---

## 📁 Project Structure

```
django-socket-with-unity/
├── game_manager/
│   ├── models.py              # ✨ Enhanced data models
│   ├── redis_queue.py         # ✨ NEW: Time-based queue
│   ├── tasks.py               # ✨ Rewritten Celery tasks
│   ├── consumers.py           # ✨ Enhanced WebSocket consumer
│   ├── views.py               # ✨ New REST API endpoints
│   ├── serializers.py         # ✨ Updated serializers
│   └── urls.py                # ✨ API routing
├── unity_scripts/
│   └── UnityWebSocketClient.cs # ✨ Complete Unity client
├── create_test_data.py        # ✨ NEW: Test data script
└── requirements.txt           # ✨ Updated dependencies
```

---

## 🎯 What Happens Automatically

1. **Every 5 seconds**: Celery checks Redis queue for due maps
2. **When map is due**: Automatically assigns to idle Unity server
3. **Unity processes**: Fetches map data, runs calculations, submits results
4. **After completion**: Map is requeued for next round (default 60s later)
5. **Every 30 seconds**: Health check detects offline servers and recovers jobs

---

## 💡 Next: Customize Your Logic

Edit `UnityWebSocketClient.cs` at line ~120:

```csharp
// 2. PROCESS MAP - THIS IS WHERE YOUR GAME LOGIC GOES
Debug.Log($"[Job] Processing map {mapId} with data: {mapData}");

// Replace this simulation with your actual map processing:
// - Load game objects based on mapData
// - Run round calculations
// - Generate results

yield return new WaitForSeconds(3f);  // Replace with actual processing time
```

---

## ✅ System is Running When...

- ✅ 4 terminals running (Redis, Django, Celery Worker, Celery Beat)
- ✅ `curl http://localhost:8000/api/queue/` returns JSON
- ✅ Unity shows "[WebSocket] Connected"
- ✅ Celery logs show "Found X due maps" every 5 seconds

---

**🎉 You're all set! The system will now automatically process maps on schedule.**
