# API Documentation - Django Socket Server

## Base URL
```
http://127.0.0.1:8000
```

---

## WebSocket Endpoints

### 1. Unity Server Connection
**URL**: `ws://127.0.0.1:8000/ws/server/{server_id}/`

**Description**: WebSocket endpoint for Unity servers to connect and communicate.

**Connection Example** (Unity C#):
```csharp
string serverId = "unity_192_168_1_100";
WebSocket ws = new WebSocket($"ws://127.0.0.1:8000/ws/server/{serverId}/");
ws.Connect();
```

**Messages from Unity to Django**:

```json
// Heartbeat (every 5 seconds)
{
  "type": "heartbeat",
  "cpu": 45.2,
  "players": 0
}

// Status Update
{
  "type": "status_update",
  "status": "busy"  // or "idle"
}

// Job Completion
{
  "type": "job_done",
  "map_id": "map_001",
  "result": { "winner": "player1", "score": 1500 },
  "next_time": 3600  // seconds until next round
}

// Error Report
{
  "type": "error",
  "error": "Failed to load map assets"
}

// Graceful Disconnect
{
  "type": "disconnect"
}
```

**Messages from Django to Unity**:

```json
// Job Assignment
{
  "type": "assign_job",
  "map_id": "map_001",
  "season_id": 1,
  "round_id": 5
}

// Administrative Command
{
  "type": "command",
  "command": {
    "type": "command",
    "action": "restart_server",
    "serverId": "unity_192_168_1_100",
    "payload": {}
  },
  "params": {}
}
```

---

## REST API Endpoints

### 2. Get Map Data
**Method**: `GET`  
**URL**: `/api/map/{map_id}/`

**Description**: Retrieve map configuration for processing.

**Example**:
```bash
curl http://127.0.0.1:8000/api/map/map_001/
```

**Response**:
```json
{
  "map_id": "map_001",
  "season_id": 1,
  "round_id": 5,
  "status": "queued",
  "next_round_time": "2025-12-10T12:00:00Z"
}
```

---

### 3. Submit Result
**Method**: `POST`  
**URL**: `/api/result/`

**Description**: Submit game results from Unity server (triggers async processing).

**Request Body**:
```json
{
  "map_id": "map_001",
  "server_id": "unity_192_168_1_100",
  "result": {
    "winner": "player1",
    "score": 1500,
    "duration": 300
  },
  "next_time": 3600
}
```

**Example**:
```bash
curl -X POST http://127.0.0.1:8000/api/result/ \
  -H "Content-Type: application/json" \
  -d '{
    "map_id": "map_001",
    "server_id": "unity_192_168_1_100",
    "result": {"winner": "player1", "score": 1500},
    "next_time": 3600
  }'
```

**Response**:
```json
{
  "status": "accepted",
  "message": "Result processing initiated"
}
```

---

### 4. List Servers
**Method**: `GET`  
**URL**: `/api/servers/`

**Description**: Get all server statuses with metrics.

**Example**:
```bash
curl http://127.0.0.1:8000/api/servers/
```

**Response**:
```json
[
  {
    "server_id": "unity_192_168_1_100",
    "server_ip": "192.168.1.100",
    "status": "idle",
    "last_heartbeat": "2025-12-10T05:00:00Z",
    "cpu_usage": 45.2,
    "ram_usage": 60.5,
    "connected_at": "2025-12-10T04:00:00Z"
  }
]
```

---

### 5. Server Detail
**Method**: `GET`  
**URL**: `/api/server/{server_id}/`

**Description**: Get detailed information about a specific server.

**Example**:
```bash
curl http://127.0.0.1:8000/api/server/unity_192_168_1_100/
```

**Response**:
```json
{
  "server_id": "unity_192_168_1_100",
  "server_ip": "192.168.1.100",
  "status": "busy",
  "current_task": "map_001",
  "last_heartbeat": "2025-12-10T05:00:00Z",
  "cpu_usage": 75.0,
  "ram_usage": 80.0
}
```

---

### 6. Queue Status
**Method**: `GET`  
**URL**: `/api/queue/`

**Description**: Get queue statistics for monitoring.

**Example**:
```bash
curl http://127.0.0.1:8000/api/queue/
```

**Response**:
```json
{
  "queue_size": 15,
  "next_due_time": "2025-12-10T06:00:00Z",
  "idle_servers": 3,
  "busy_servers": 2,
  "offline_servers": 1,
  "queued_maps": 10,
  "processing_maps": 5
}
```

---

### 7. Send Command
**Method**: `POST`  
**URL**: `/api/command/`

**Description**: Manually send commands to Unity servers via WebSocket.

**Request Body**:
```json
{
  "server_id": "unity_192_168_1_100",
  "action": "restart_server",
  "payload": {}
}
```

**Available Actions**:
- `restart_server` - Restart the Unity server
- `stop_game` - Cancel current task
- Custom actions (defined in Unity)

**Example**:
```bash
curl -X POST http://127.0.0.1:8000/api/command/ \
  -H "Content-Type: application/json" \
  -d '{
    "server_id": "unity_192_168_1_100",
    "action": "restart_server",
    "payload": {}
  }'
```

**Response (Success)**:
```json
{
  "status": "success",
  "message": "Command sent to unity_192_168_1_100"
}
```

**Response (Error)**:
```json
{
  "error": "Missing server_id or action"
}
```

---

## Web Interface

### 8. Dashboard
**Method**: `GET`  
**URL**: `/dashboard/`

**Description**: Admin dashboard showing server status and map queue.

**Access**: Open in browser
```
http://127.0.0.1:8000/dashboard/
```

**Features**:
- Real-time server status monitoring
- Active maps and queue display
- Server control buttons (Restart, Cancel Task)
- Auto-refresh every 5 seconds

---

### 9. Django Admin
**Method**: `GET`  
**URL**: `/admin/`

**Description**: Django admin panel for database management.

**Access**: 
```
http://127.0.0.1:8000/admin/
```

---

## Error Responses

All endpoints return standard HTTP status codes:

**400 Bad Request**:
```json
{
  "error": "Missing required field: map_id"
}
```

**404 Not Found**:
```json
{
  "error": "Map not found"
}
```

**500 Internal Server Error**:
```json
{
  "error": "Failed to send command"
}
```

---

## Testing with cURL

**Test WebSocket** (requires `websocat`):
```bash
# Install websocat
# Windows: choco install websocat
# Linux/Mac: cargo install websocat

# Connect
websocat ws://127.0.0.1:8000/ws/server/test_server/

# Send heartbeat
{"type": "heartbeat", "cpu": 50.0}
```

**Test REST API**:
```bash
# List all servers
curl http://127.0.0.1:8000/api/servers/

# Get queue status
curl http://127.0.0.1:8000/api/queue/

# Send command
curl -X POST http://127.0.0.1:8000/api/command/ \
  -H "Content-Type: application/json" \
  -d '{"server_id": "test_server", "action": "restart_server"}'
```

---

## Unity Integration Example

```csharp
using WebSocketSharp;
using Newtonsoft.Json;

public class ServerConnection
{
    private WebSocket ws;
    
    public void Connect(string serverId)
    {
        ws = new WebSocket($"ws://127.0.0.1:8000/ws/server/{serverId}/");
        
        ws.OnOpen += (sender, e) => {
            Debug.Log("Connected to orchestrator");
            SendHeartbeat();
        };
        
        ws.OnMessage += (sender, e) => {
            var data = JsonConvert.DeserializeObject<Dictionary<string, object>>(e.Data);
            HandleMessage(data);
        };
        
        ws.Connect();
    }
    
    private void SendHeartbeat()
    {
        var heartbeat = new {
            type = "heartbeat",
            cpu = SystemInfo.processorCount,
            players = 0
        };
        ws.Send(JsonConvert.SerializeObject(heartbeat));
    }
    
    private void HandleMessage(Dictionary<string, object> data)
    {
        if (data["type"].ToString() == "assign_job") {
            string mapId = data["map_id"].ToString();
            ProcessJob(mapId);
        }
    }
}
```
