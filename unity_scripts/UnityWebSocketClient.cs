using UnityEngine;
using WebSocketSharp;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using System.Collections;
using UnityEngine.Networking;
using System.Text;

public class UnityWebSocketClient : MonoBehaviour
{
    [Header("Connection Settings")]
    public string backendWsUrl = "ws://localhost:8000/ws/server/";
    public string backendApiUrl = "http://localhost:8000";
    public string serverId = "unity_server_01";
    
    [Header("Heartbeat Settings")]
    public float heartbeatInterval = 5f;
    
    private WebSocket ws;
    private bool isProcessing = false;

    void Start()
    {
        ConnectToBackend();
        StartCoroutine(SendHeartbeatRoutine());
    }

    void ConnectToBackend()
    {
        string url = backendWsUrl + serverId + "/";
        ws = new WebSocket(url);

        ws.OnOpen += (sender, e) =>
        {
            Debug.Log($"[WebSocket] Connected to {url}");
            SendStatusUpdate("idle");
        };

        ws.OnMessage += (sender, e) =>
        {
            Debug.Log($"[WebSocket] Message Received: {e.Data}");
            HandleMessage(e.Data);
        };

        ws.OnClose += (sender, e) =>
        {
            Debug.LogWarning($"[WebSocket] Closed: {e.Reason}");
            // Auto-reconnect after 5 seconds
            Invoke("ConnectToBackend", 5f);
        };

        ws.OnError += (sender, e) =>
        {
            Debug.LogError($"[WebSocket] Error: {e.Message}");
        };

        ws.Connect();
    }

    void HandleMessage(string jsonMessage)
    {
        try
        {
            var data = JObject.Parse(jsonMessage);
            string type = (string)data["type"];

            if (type == "assign_job")
            {
                // New job assignment from Django
                string mapId = (string)data["map_id"];
                int roundId = (int)data["round_id"];
                int seasonId = (int)data["season_id"];
                JObject mapData = (JObject)data["map_data"];
                
                Debug.Log($"[Job] Assigned: Map {mapId}, Round {roundId}, Season {seasonId}");
                StartCoroutine(ProcessMapJob(mapId, roundId, seasonId, mapData));
            }
            else if (type == "command")
            {
                // Manual command from dashboard
                string action = (string)data["action"];
                Debug.Log($"[Command] Received: {action}");
                HandleCommand(action, data);
            }
            else
            {
                Debug.LogWarning($"[WebSocket] Unknown message type: {type}");
            }
        }
        catch (System.Exception ex)
        {
            Debug.LogError($"[WebSocket] Error parsing message: {ex.Message}");
        }
    }

    IEnumerator ProcessMapJob(string mapId, int roundId, int seasonId, JObject mapData)
    {
        if (isProcessing)
        {
            Debug.LogWarning("[Job] Already processing a job, rejecting new assignment");
            yield break;
        }

        isProcessing = true;
        SendStatusUpdate("busy");

        Debug.Log($"[Job] Starting processing for map {mapId}");

        // 1. Fetch full map data from API (optional, already have basic data)
        string apiUrl = $"{backendApiUrl}/api/map/{mapId}/";
        using (UnityWebRequest webRequest = UnityWebRequest.Get(apiUrl))
        {
            yield return webRequest.SendWebRequest();

            if (webRequest.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError($"[Job] Error fetching map data: {webRequest.error}");
                SendError(mapId, $"Failed to fetch map data: {webRequest.error}");
                isProcessing = false;
                SendStatusUpdate("idle");
                yield break;
            }
            
            Debug.Log($"[Job] Map Data Retrieved: {webRequest.downloadHandler.text}");
            // You can parse additional data here if needed
        }

        // 2. PROCESS MAP - THIS IS WHERE YOUR GAME LOGIC GOES
        Debug.Log($"[Job] Processing map {mapId} with data: {mapData}");
        
        // Simulate calculation (replace with your actual processing)
        yield return new WaitForSeconds(3f);
        
        // 3. Create result data
        var resultData = new JObject
        {
            ["success"] = true,
            ["calculations_completed"] = 100,
            ["timestamp"] = System.DateTime.UtcNow.ToString("o"),
            // Add your actual calculation results here
        };
        
        // 4. Calculate next round time (e.g., 60 seconds from now)
        int nextTimeSeconds = 60; // Adjust based on your game logic
        
        // 5. Submit results to API
        yield return SubmitResults(mapId, seasonId, roundId + 1, resultData, nextTimeSeconds);
        
        // 6. Notify WebSocket of completion
        SendJobDone(mapId, resultData, nextTimeSeconds);
        
        // 7. Back to idle
        isProcessing = false;
        SendStatusUpdate("idle");
        
        Debug.Log($"[Job] Completed: {mapId}");
    }

    IEnumerator SubmitResults(string mapId, int seasonId, int roundId, JObject result, int nextTime)
    {
        string apiUrl = $"{backendApiUrl}/api/result/";
        
        var payload = new JObject
        {
            ["map_id"] = mapId,
            ["server_id"] = serverId,
            ["result"] = result,
            ["next_time"] = nextTime
        };
        
        Debug.Log($"[API] Submitting results: {payload}");
        
        var request = new UnityWebRequest(apiUrl, "POST");
        byte[] bodyRaw = Encoding.UTF8.GetBytes(payload.ToString());
        request.uploadHandler = new UploadHandlerRaw(bodyRaw);
        request.downloadHandler = new DownloadHandlerBuffer();
        request.SetRequestHeader("Content-Type", "application/json");
        
        yield return request.SendWebRequest();
        
        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError($"[API] Failed to submit results: {request.error}");
        }
        else
        {
            Debug.Log($"[API] Results submitted successfully");
        }
    }

    IEnumerator SendHeartbeatRoutine()
    {
        while (true)
        {
            yield return new WaitForSeconds(heartbeatInterval);
            
            if (ws != null && ws.IsAlive)
            {
                var payload = new JObject
                {
                    ["type"] = "heartbeat",
                    ["cpu"] = Random.Range(10f, 80f), // Replace with actual CPU usage
                    ["players"] = 0 // Replace with actual player count
                };
                
                ws.Send(payload.ToString());
                // Don't log every heartbeat to avoid spam
            }
        }
    }

    void SendStatusUpdate(string status)
    {
        if (ws != null && ws.IsAlive)
        {
            var message = new JObject
            {
                ["type"] = "status_update",
                ["status"] = status
            };
            
            ws.Send(message.ToString());
            Debug.Log($"[Status] Updated to: {status}");
        }
    }
    
    void SendJobDone(string mapId, JObject result, int nextTime)
    {
        if (ws != null && ws.IsAlive)
        {
            var message = new JObject
            {
                ["type"] = "job_done",
                ["map_id"] = mapId,
                ["result"] = result,
                ["next_time"] = nextTime
            };
            
            ws.Send(message.ToString());
            Debug.Log($"[WebSocket] Job done notification sent for {mapId}");
        }
    }

    void SendError(string mapId, string errorMessage)
    {
        if (ws != null && ws.IsAlive)
        {
            var message = new JObject
            {
                ["type"] = "error",
                ["map_id"] = mapId,
                ["error"] = errorMessage
            };
            
            ws.Send(message.ToString());
            Debug.LogError($"[WebSocket] Error notification sent: {errorMessage}");
        }
    }

    void HandleCommand(string action, JObject data)
    {
        // Handle manual commands from dashboard
        switch (action)
        {
            case "ping":
                Debug.Log("[Command] Ping received, sending pong");
                SendStatusUpdate("idle");
                break;
            case "restart":
                Debug.Log("[Command] Restart requested");
                // Implement restart logic
                break;
            default:
                Debug.LogWarning($"[Command] Unknown action: {action}");
                break;
        }
    }

    void OnDestroy()
    {
        if (ws != null)
        {
            ws.Close();
        }
    }

    void OnApplicationQuit()
    {
        if (ws != null)
        {
            ws.Close();
        }
    }
}
