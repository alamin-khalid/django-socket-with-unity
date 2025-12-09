using UnityEngine;
using WebSocketSharp;
using Newtonsoft.Json.Linq;
using System.Collections;
using UnityEngine.Networking;
using System;
using System.Net;

public class UnityWebSocketClient : MonoBehaviour
{
    [Header("Backend Configuration")] public string backendWsUrl = "ws://127.0.0.1:8000/ws/server/";
    public string backendApiUrl = "http://127.0.0.1:8000";

    [Header("Server Identity")] public string serverId = ""; // Will auto-generate from public IP

    private WebSocket ws;
    private string publicIP = "";
    private bool isProcessing = false;

    private void Start()
    {
        StartCoroutine(InitializeAndConnect());
    }

    private IEnumerator InitializeAndConnect()
    {
        // 1. Get public IP first
        yield return StartCoroutine(GetPublicIP());

        // 2. Set serverId if not manually configured
        if (string.IsNullOrEmpty(serverId))
        {
            serverId = $"unity_{publicIP.Replace(".", "_")}";
        }

        Debug.Log($"[Init] Server ID: {serverId}, Public IP: {publicIP}");

        // 3. Connect to WebSocket
        Connect();

        // 4. Start heartbeat
        StartCoroutine(SendHeartbeat());
    }

    // ================================================================
    // GET PUBLIC IP
    // ================================================================

    private IEnumerator GetPublicIP()
    {
        Debug.Log("[IP] Fetching public IP...");

        // Try primary service
        UnityWebRequest request = UnityWebRequest.Get("https://api.ipify.org?format=text");
        yield return request.SendWebRequest();

        if (request.result == UnityWebRequest.Result.Success)
        {
            publicIP = request.downloadHandler.text.Trim();
            Debug.Log($"[IP] Public IP detected: {publicIP}");
        }
        else
        {
            Debug.LogWarning($"[IP] Primary service failed: {request.error}");

            // Fallback to secondary service
            request = UnityWebRequest.Get("https://checkip.amazonaws.com");
            yield return request.SendWebRequest();

            if (request.result == UnityWebRequest.Result.Success)
            {
                publicIP = request.downloadHandler.text.Trim();
                Debug.Log($"[IP] Public IP detected (fallback): {publicIP}");
            }
            else
            {
                Debug.LogError($"[IP] Failed to get public IP: {request.error}");
                publicIP = "unknown";
            }
        }
    }

    // ================================================================
    // WEBSOCKET CONNECTION
    // ================================================================

    void Connect()
    {
        string wsUrl = $"{backendWsUrl}{serverId}/";
        Debug.Log($"[WebSocket] Connecting to {wsUrl}...");

        ws = new WebSocket(wsUrl);

        ws.OnOpen += (sender, e) => { Debug.Log($"[WebSocket] ✅ Connected as {serverId}"); };

        ws.OnMessage += (sender, e) =>
        {
            Debug.Log($"[WebSocket] ⬇ Received: {e.Data}");
            HandleMessage(e.Data);
        };

        ws.OnError += (sender, e) => { Debug.LogError($"[WebSocket] ❌ Error: {e.Message}"); };

        ws.OnClose += (sender, e) =>
        {
            Debug.LogWarning($"[WebSocket] Disconnected. Code: {e.Code}, Reason: {e.Reason}");

            // Auto-reconnect after 5 seconds
            Invoke(nameof(Connect), 5f);
        };

        ws.Connect();
    }

    // ================================================================
    // MESSAGE HANDLING (Django → Unity)
    // ================================================================

    void HandleMessage(string message)
    {
        try
        {
            JObject data = JObject.Parse(message);
            string messageType = data["type"]?.ToString();

            switch (messageType)
            {
                case "assign_job":
                    OnJobAssignment(data);
                    break;

                case "command":
                    OnCommand(data);
                    break;

                default:
                    Debug.LogWarning($"[WebSocket] Unknown message type: {messageType}");
                    break;
            }
        }
        catch (Exception ex)
        {
            Debug.LogError($"[WebSocket] Failed to parse message: {ex.Message}");
        }
    }

    void OnJobAssignment(JObject data)
    {
        if (isProcessing)
        {
            Debug.LogWarning("[Job] Already processing, ignoring new assignment");
            return;
        }

        string mapId = data["map_id"]?.ToString();
        int roundId = data["round_id"]?.ToObject<int>() ?? 0;
        int seasonId = data["season_id"]?.ToObject<int>() ?? 1;

        Debug.Log($"[Job] 📋 Assigned: Map {mapId}, Season {seasonId}, Round {roundId}");

        // Update status to busy
        SendStatusUpdate("busy");

        // Start processing
        StartCoroutine(ProcessMapJob(mapId, seasonId, roundId));
    }

    void OnCommand(JObject data)
    {
        string command = data["command"]?.ToString();
        Debug.Log($"[Command] Received: {command}");

        // Handle commands like restart_server, stop_server, etc.
        switch (command)
        {
            case "restart_server":
                Debug.Log("[Command] Restarting server...");
                // Implement restart logic
                break;

            case "stop_server":
                Debug.Log("[Command] Stopping server...");
                Application.Quit();
                break;
        }
    }

    // ================================================================
    // JOB PROCESSING WORKFLOW
    // ================================================================

    IEnumerator ProcessMapJob(string mapId, int seasonId, int roundId)
    {
        isProcessing = true;

        Debug.Log($"[Job] 🔄 Starting processing for {mapId}");

        // 1. FETCH MAP DATA FROM API


        // 2. SUBMIT RESULTS TO API
        yield return StartCoroutine(SubmitResults(mapId, null, 0));

        // 3. NOTIFY WEBSOCKET WE'RE DONE
        SendJobDone(mapId, null, 0);

        // 4. BACK TO IDLE
        SendStatusUpdate("idle");
        isProcessing = false;

        Debug.Log($"[Job] ✅ Completed {mapId}");
    }

    // ================================================================
    // API CALLS
    // ================================================================

    public IEnumerator SubmitResults(string mapId, JObject result, int nextTimeSeconds)
    {
        string apiUrl = $"{backendApiUrl}/api/result/";

        JObject payload = new JObject
        {
            ["map_id"] = mapId,
            ["server_id"] = serverId,
            ["result"] = result,
            ["next_time"] = nextTimeSeconds
        };

        Debug.Log($"[API] Submitting results to {apiUrl}");

        UnityWebRequest request = new UnityWebRequest(apiUrl, "POST");
        byte[] bodyRaw = System.Text.Encoding.UTF8.GetBytes(payload.ToString());
        request.uploadHandler = new UploadHandlerRaw(bodyRaw);
        request.downloadHandler = new DownloadHandlerBuffer();
        request.SetRequestHeader("Content-Type", "application/json");

        yield return request.SendWebRequest();

        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError($"[API] ❌ Failed to submit results: {request.error}");
        }
        else
        {
            Debug.Log($"[API] ✅ Results submitted successfully");
        }
    }

    // ================================================================
    // WEBSOCKET MESSAGES (Unity → Django)
    // ================================================================

    IEnumerator SendHeartbeat()
    {
        while (true)
        {
            if (isProcessing)
            {
                // Wait until isProcessing becomes false
                yield return new WaitWhile(() => isProcessing);
            }
            else
            {
                yield return new WaitForSeconds(5f);
            }


            if (ws != null && ws.IsAlive)
            {
                float cpuUsage = UnityEngine.Random.Range(30f, 60f); // Mock CPU usage

                JObject message = new JObject
                {
                    ["type"] = "heartbeat",
                    ["cpu"] = cpuUsage,
                    ["players"] = 0
                };

                ws.Send(message.ToString());
                // Debug.Log($"[Heartbeat] Sent: CPU {cpuUsage:F1}%");
            }
        }
    }

    void SendStatusUpdate(string status)
    {
        if (ws == null || !ws.IsAlive) return;

        JObject message = new JObject
        {
            ["type"] = "status_update",
            ["status"] = status
        };

        ws.Send(message.ToString());
        Debug.Log($"[Status] 🔄 Changed to: {status}");
    }

    void SendJobDone(string mapId, JObject result, int nextTimeSeconds)
    {
        if (ws == null || !ws.IsAlive) return;

        JObject message = new JObject
        {
            ["type"] = "job_done",
            ["map_id"] = mapId,
            ["result"] = result,
            ["next_time"] = nextTimeSeconds
        };

        ws.Send(message.ToString());
        Debug.Log($"[WebSocket] ⬆ Sent job_done for {mapId}");
    }

    void SendError(string error)
    {
        if (ws == null || !ws.IsAlive) return;

        JObject message = new JObject
        {
            ["type"] = "error",
            ["error"] = error
        };

        ws.Send(message.ToString());
        Debug.LogError($"[Error] Sent: {error}");
    }

    void SendDisconnect()
    {
        if (ws == null || !ws.IsAlive) return;

        JObject message = new JObject
        {
            ["type"] = "disconnect",
            ["server_id"] = serverId
        };

        ws.Send(message.ToString());
    }

    // ================================================================
    // CLEANUP
    // ================================================================

    void OnApplicationQuit()
    {
        SendDisconnect();
        ws?.Close();
    }

    void OnDestroy()
    {
        SendDisconnect();
        ws?.Close();
    }
}