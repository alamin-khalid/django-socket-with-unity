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
  "idle_cpu": 15.2,
  "idle_ram": 40.5,
  "max_cpu": 75.0,
  "max_ram": 85.0,
  "disk": 60.0
}

// Status Update
{
  "type": "status_update",
  "status": "busy"  // or "idle"
}

// Job Completion
{
  "type": "job_done",
  "planet_id": "planet_001",
  "next_round_time": "2025-12-18T12:00:00Z"  // ISO 8601 datetime string for next round
}

// Job Skipped (round time not expired yet)
{
  "type": "job_skipped",
  "planet_id": "planet_001",
  "next_round_time": "2025-12-18T12:00:00Z",
  "reason": "Round time remaining: 5.2 minutes"
}

// Error Report
{
  "type": "error",
  "planet_id": "planet_001",
  "error": "Failed to load planet assets"
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
  "planet_id": "planet_001",
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

### 2. Get Planet Data
**Method**: `GET`  
**URL**: `/api/planet/{planet_id}/`  
**Status**: 🔒 *Reserved for later use*

**Description**: Retrieve planet configuration for processing.

**Example**:
```bash
curl http://127.0.0.1:8000/api/planet/planet_001/
```

**Response**:
```json
{
  "planet_id": "planet_001",
  "season_id": 1,
  "round_id": 5,
  "current_round_number": 5,
  "status": "queued",
  "next_round_time": "2025-12-10T12:00:00Z",
  "last_processed": null,
  "processing_server_id": null
}
```

---

### 3. Create Planet
**Method**: `POST`  
**URL**: `/api/planet/create/` or `/api/map/create/`

**Description**: Create a new planet by providing planet_id (or map_id) and season.

**Request Body**:
```json
{
  "map_id": "79001",
  "season_id": 34
}
```

Or alternatively:
```json
{
  "planet_id": "planet_123",
  "season_id": 1
}
```

**Required Fields**:
- `planet_id` OR `map_id` (string): Unique planet identifier (`map_id` is an alias for `planet_id`)
  - Must contain only letters, numbers, underscores, and hyphens
  - Maximum 100 characters
- `season_id` (integer): Season identifier

**Optional Fields**:
- `round_id` (integer): Round identifier, defaults to 0 if not provided
- `current_round_number` (integer): Current round number, defaults to 0 if not provided

**Note**: Created planets are automatically added to the processing queue with `next_round_time` set to **NOW**, so they will be picked up by idle servers immediately.

**Example**:
```bash
curl -X POST http://127.0.0.1:8000/api/planet/create/ \
  -H "Content-Type: application/json" \
  -d '{
    "planet_id": "planet_123",
    "season_id": 1
  }'
```

**Response (Success - 201 Created)**:
```json
{
  "planet_id": "planet_123",
  "season_id": 1,
  "round_id": 0,
  "current_round_number": 0,
  "next_round_time": "2025-12-18T01:46:44Z",
  "status": "queued",
  "last_processed": null,
  "processing_server_id": null
}
```

**Response (Duplicate - 409 Conflict)**:
```json
{
  "error": "Planet with planet_id \"planet_123\" already exists"
}
```

**Response (Missing Field - 400 Bad Request)**:
```json
{
  "error": "planet_id is required"
}
```

**Response (Validation Error - 400 Bad Request)**:
```json
{
  "next_round_time": ["Datetime has wrong format. Use one of these formats instead: YYYY-MM-DDThh:mm[:ss[.uuuuuu]][+HH:MM|-HH:MM|Z]."]
}
```

---

### 4. Remove Planet
**Method**: `DELETE`  
**URL**: `/api/planet/remove/{planet_id}/` or `/api/map/remove/{planet_id}/`

**Description**: Remove a planet from the system. The planet will also be removed from the Redis processing queue.

**Example**:
```bash
curl -X DELETE http://127.0.0.1:8000/api/planet/remove/planet_123/
```

**Response (Success - 200 OK)**:
```json
{
  "status": "success",
  "message": "Planet \"planet_123\" has been removed"
}
```

**Response (Not Found - 404)**:
```json
{
  "error": "Planet \"planet_123\" not found"
}
```

**Response (Processing - 409 Conflict)**:
```json
{
  "error": "Cannot remove planet \"planet_123\" while it is being processed"
}
```

> [!NOTE]
> Planets that are currently being processed (status = `processing`) cannot be removed. Wait for the job to complete or cancel it first.

---

### 5. Submit Result
**Method**: `POST`  
**URL**: `/api/result/`  
**Status**: 🔒 *Reserved for later use*

**Description**: Submit game results from Unity server (triggers async processing).

**Request Body**:
```json
{
  "planet_id": "planet_001",
  "server_id": "unity_192_168_1_100",
  "next_round_time": "2025-12-18T12:00:00Z"
}
```

**Required Fields**:
- `planet_id` (string): Planet identifier
- `server_id` (string): Server identifier
- `next_round_time` (string): ISO 8601 datetime string for when the next round should be processed

**Example**:
```bash
curl -X POST http://127.0.0.1:8000/api/result/ \
  -H "Content-Type: application/json" \
  -d '{
    "planet_id": "planet_001",
    "server_id": "unity_192_168_1_100",
    "next_round_time": "2025-12-18T12:00:00Z"
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

### 6. List Servers
**Method**: `GET`  
**URL**: `/api/servers/`  
**Status**: 🔒 *Reserved for later use*

**Description**: Get all server statuses with metrics.

**Example**:
```bash
curl http://127.0.0.1:8000/api/servers/
```

**Response**:
```json
[
  {
    "id": 1,
    "server_id": "unity_192_168_1_100",
    "server_ip": "192.168.1.100",
    "status": "idle",
    "last_heartbeat": "2025-12-10T05:00:00Z",
    "idle_cpu_usage": 15.2,
    "idle_ram_usage": 40.5,
    "max_cpu_usage": 75.0,
    "max_ram_usage": 85.0,
    "disk_usage": 60.0,
    "current_task_id": null,
    "connected_at": "2025-12-10T04:00:00Z",
    "disconnected_at": null,
    "total_assigned_planet": 50,
    "total_completed_planet": 45,
    "total_failed_planet": 5,
    "uptime_seconds": 3600
  }
]
```

---

### 7. Server Detail
**Method**: `GET`  
**URL**: `/api/server/{server_id}/`  
**Status**: 🔒 *Reserved for later use*

**Description**: Get detailed information about a specific server.

**Example**:
```bash
curl http://127.0.0.1:8000/api/server/unity_192_168_1_100/
```

**Response**:
```json
{
  "id": 1,
  "server_id": "unity_192_168_1_100",
  "server_ip": "192.168.1.100",
  "status": "busy",
  "last_heartbeat": "2025-12-10T05:00:00Z",
  "idle_cpu_usage": 15.2,
  "idle_ram_usage": 40.5,
  "max_cpu_usage": 75.0,
  "max_ram_usage": 85.0,
  "disk_usage": 60.0,
  "current_task_id": "planet_001",
  "connected_at": "2025-12-10T04:00:00Z",
  "disconnected_at": null,
  "total_assigned_planet": 50,
  "total_completed_planet": 45,
  "total_failed_planet": 5,
  "uptime_seconds": 3600
}
```

---

### 8. Queue Status
**Method**: `GET`  
**URL**: `/api/queue/`  
**Status**: 🔒 *Reserved for later use*

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
  "queued_planets": 10,
  "processing_planets": 5
}
```

---

### 9. Send Command
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

### 10. Force Assign
**Method**: `POST`  
**URL**: `/api/force-assign/`

**Description**: Manually trigger planet assignment to idle servers.

**Example**:
```bash
curl -X POST http://127.0.0.1:8000/api/force-assign/
```

**Response (Success)**:
```json
{
  "status": "success",
  "message": "Assignment triggered"
}
```

---

## Web Interface

### 11. Dashboard
**Method**: `GET`  
**URL**: `/dashboard/`

**Description**: Admin dashboard showing server status and planet queue.

**Access**: Open in browser
```
http://127.0.0.1:8000/dashboard/
```

**Features**:
- Real-time server status monitoring
- Active planets and queue display
- Server control buttons (Restart, Cancel Task)
- Scrollable tables with sticky headers
- Auto-refresh (configurable 2-120 seconds)
- Dark/Light mode toggle

---

### 12. Task History Page
**Method**: `GET`  
**URL**: `/task-history/`

**Description**: Full task history with search and pagination.

**Access**: Open in browser
```
http://127.0.0.1:8000/task-history/
```

**Features**:
- View all task history (not limited to 50)
- Real-time search filter (Planet ID, Server, Status)
- Client-side pagination (10/25/50/100/All per page)
- Scrollable table with sticky headers
- Dark/Light mode toggle

---

### 13. Django Admin
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
  "error": "Missing required field: planet_id"
}
```

**404 Not Found**:
```json
{
  "error": "Planet not found"
}
```

**500 Internal Server Error**:
```json
{
  "error": "Failed to send command"
}
```

---

## ⚠️ Important Notes

### Unity Client Implementation

> [!IMPORTANT]
> The Unity client script must send the correct field names in WebSocket messages to match the backend API expectations.

> [!CAUTION]
> **CRITICAL:** The current Unity client is missing the `SendJobDone` method and has incorrect server ID format. Without fixing these, the system will not function properly.

**Critical Requirements for `job_done` message:**

1. **Field Names Must Match:**
   - Use `planet_id` (this is the correct field name)
   - Use `next_round_time` (NOT `next_calculation_time`)

2. **DateTime Format:**
   - `next_round_time` must be an ISO 8601 datetime string
   - Example: `"2025-12-18T12:00:00Z"` or `"2025-12-18T12:00:00+00:00"`
   - In C#, use: `nextRoundTime.ToString("O")` or `nextRoundTime.ToUniversalTime().ToString("o")`

3. **Status Updates:**
   - After sending `job_done`, the Unity client should send a `status_update` message with `"status": "idle"` to allow new assignments
   - Alternatively, ensure your game manager calls `SendStatusUpdate("idle")` after job completion

**Example Unity Implementation:**
```csharp
// ⚠️ THIS METHOD IS MISSING FROM CURRENT UnityWebSocketClient.cs
// Add this to the "OUTGOING MESSAGES" section around line 307

public void SendJobDone(string planetId, DateTime nextRoundTime)
{
    if (ws == null || !ws.IsAlive) return;

    ws.Send(new JObject
    {
        ["type"] = "job_done",
        ["planet_id"] = planetId,  // ✅ Correct field name
        ["next_round_time"] = nextRoundTime.ToString("O")  // ✅ ISO 8601 format
    }.ToString());
    
    Debug.Log($"[Job Done] ✅ Sent completion for {planetId}, next: {nextRoundTime:O}");
    
    // Mark server as idle for new assignments
    SendStatusUpdate("idle");
}
```

**Additional Required Fixes:**

1. **Fix Server ID Format (line 62):**
```csharp
// ❌ Current (wrong):
serverId = publicIP.Replace(".", "_");

// ✅ Fixed:
serverId = $"unity_{publicIP.Replace(".", "_")}";
```

2. **Update SendFailed consistency (line 315):**
```csharp
// Use "planet_id" for consistency
["planet_id"] = planetId.ToString(),
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
# Create a planet
curl -X POST http://127.0.0.1:8000/api/planet/create/ \
  -H "Content-Type: application/json" \
  -d '{"planet_id": "planet_001", "season_id": 1}'

# Remove a planet
curl -X DELETE http://127.0.0.1:8000/api/planet/remove/planet_001/

# Force assignment
curl -X POST http://127.0.0.1:8000/api/force-assign/

# Send command
curl -X POST http://127.0.0.1:8000/api/command/ \
  -H "Content-Type: application/json" \
  -d '{"server_id": "test_server", "action": "restart_server"}'
```

---

## Unity Integration Example

> [!WARNING]
> The code below shows the **intended** implementation. The current `UnityWebSocketClient.cs` has been refactored and is missing critical functionality. See the Important Notes section above for required fixes.

**Updated Integration Pattern:**

```csharp
using WebSocketSharp;
using Newtonsoft.Json.Linq;
using System;

public class ServerConnection : MonoBehaviour
{
    private UnityWebSocketClient wsClient;
    
    private void Start()
    {
        wsClient = GetComponent<UnityWebSocketClient>();
        StartCoroutine(wsClient.InitializeAndConnect());
    }
    
    // Called when job processing completes
    private void OnJobComplete(string planetId, DateTime nextRoundTime)
    {
        // ⚠️ This method must be added to UnityWebSocketClient
        wsClient.SendJobDone(planetId, nextRoundTime);
    }
    
    // Handle errors during processing
    private void OnJobError(int planetId, string errorMessage)
    {
        wsClient.SendFailed(planetId, errorMessage);
    }
}
```

**Key Features of Refactored Client:**
- ✅ Automatic reconnection with exponential backoff (5s → 30s max)
- ✅ Thread-safe message handling via MainThreadDispatcher (already in project)
- ✅ Improved error tracking and logging
- ✅ Graceful disconnect on application quit
- ❌ Missing SendJobDone method (must be added)
- ❌ Wrong server ID format (must be fixed)
