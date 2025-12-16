using UnityEngine;
using WebSocketSharp;
using Newtonsoft.Json.Linq;
using System.Collections;
using UnityEngine.Networking;
using System;
using System.Net;
using System.Threading.Tasks;


[RequireComponent(typeof(PerformanceTracker))]
public class UnityWebSocketClient : MonoBehaviour
{
    [Header("Backend Configuration")] public string backendWsUrl = "ws://http://103.12.214.244/ws/server/";

    // Will auto-generate from public IP
    [Header("Server Identity")] public string serverId;


    private WebSocket ws;
    private string publicIP = "";


    public float heartbeatTime;

    private WaitForSeconds _heartbeat;

    public bool IsInitialized { get; private set; }

    public PerformanceTracker performanceTracker;


    private void Awake()
    {
        IsInitialized = false;

        _heartbeat = new WaitForSeconds(heartbeatTime);

        if (performanceTracker == null)
        {
            performanceTracker = GetComponent<PerformanceTracker>();
        }
    }

    public IEnumerator InitializeAndConnect()
    {
        // 1. Get public IP first
        yield return StartCoroutine(GetPublicIP());

        // 2. Set serverId
        serverId = $"unity_{publicIP.Replace(".", "_")}";

        Debug.Log($"[Init] Server ID: {serverId}, Public IP: {publicIP}");

        // 3. Connect to WebSocket
        _ = Connect();

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

    private Task Connect()
    {
        string wsUrl = $"{backendWsUrl}{serverId}/";
        Debug.Log($"[WebSocket] Connecting to {wsUrl}...");

        ws = new WebSocket(wsUrl);

        ws.OnOpen += (sender, e) =>
        {
            IsInitialized = true;
            Debug.Log($"[WebSocket] ✅ Connected as {serverId}");
        };

        ws.OnMessage += (sender, e) =>
        {
            Debug.Log($"[WebSocket] ⬇ Received: {e.Data}");
            HandleMessage(e.Data);
        };

        ws.OnError += (sender, e) => { Debug.LogError($"[WebSocket] ❌ Error: {e.Message}"); };

        ws.OnClose += (sender, e) =>
        {
            IsInitialized = false;
            Debug.LogWarning($"[WebSocket] Disconnected. Code: {e.Code}, Reason: {e.Reason}");
        };

        ws.Connect();
        return Task.CompletedTask;
    }

    // ================================================================
    // MESSAGE HANDLING (Django → Unity)
    // ================================================================

    private void HandleMessage(string message)
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
                    OnCommandReceived(data);
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

    private void OnJobAssignment(JObject data)
    {
        if (PinoWorldManager.Instance.IsSystemBusy)
        {
            Debug.LogWarning("[Job] Already processing, ignoring new assignment");
            return;
        }


        PlanetCalculateOrder _PlanetCalculateOrder = new PlanetCalculateOrder()
        {
            planetId = int.Parse(data["map_id"]?.ToString() ?? string.Empty),
            roundId = data["round_id"]?.ToObject<int>() ?? 0,
            seasonId = data["season_id"]?.ToObject<int>() ?? 0,
        };


        if (_PlanetCalculateOrder.planetId <= 0)
        {
            Debug.Log("Invalid mapId");
            return;
        }

        if (_PlanetCalculateOrder.roundId <= 0)
        {
            Debug.Log("Invalid roundId");
            return;
        }

        if (_PlanetCalculateOrder.seasonId <= 0)
        {
            Debug.Log("Invalid seasonId");
            return;
        }

        Debug.Log($"[Job] 📋 Assigned: Map {_PlanetCalculateOrder.planetId}, Season {_PlanetCalculateOrder.seasonId}, Round {_PlanetCalculateOrder.roundId}");

        // Update status to busy
        SendStatusUpdate("busy");

        // Start processing
        _ = PinoWorldManager.Instance.OnPlanetCalculateOrderReceive(_PlanetCalculateOrder);
    }

    private void OnCommandReceived(JObject data)
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
    // WEBSOCKET MESSAGES (Unity → Django)
    // ================================================================

    private IEnumerator SendHeartbeat()
    {
        while (Application.isPlaying)
        {
            yield return _heartbeat;

            if (ws != null && ws.IsAlive)
            {
                JObject message = new JObject
                {
                    ["type"] = "heartbeat",
                    ["idle_cpu"] = performanceTracker.idlePeakCPU,
                    ["max_cpu"] = performanceTracker.taskPeakCPU,
                    ["idle_ram"] = performanceTracker.idlePeakRAM,
                    ["max_ram"] = performanceTracker.taskPeakRAM,
                    ["disk"] = performanceTracker.currentDisk
                };

                ws.Send(message.ToString());
            }
        }
    }

    public void SendStatusUpdate(string status)
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

    public void SendJobDone(int planetID, DateTime nextRoundTime, string tilesJson)
    {
        if (ws == null || !ws.IsAlive) return;

        JObject message = new JObject
        {
            ["type"] = "job_done",
            ["planet_id"] = planetID,
            ["next_calculation_time"] = nextRoundTime,
            ["tiles_json"] = tilesJson
        };

        ws.Send(message.ToString());
        Debug.Log($"[WebSocket] ⬆ Sent job_done for {planetID}");
    }

    public void SendError(string error)
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

    public void SendFailed(int planetID, string cause)
    {
        if (ws == null || !ws.IsAlive) return;

        JObject message = new JObject
        {
            ["type"] = "error",
            ["planet_id"] = planetID,
            ["error"] = cause
        };

        ws.Send(message.ToString());
        Debug.LogError($"[Failed] Sent: {cause}");
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

    private void OnDisable()
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


public class PlanetCalculateOrder
{
    public int planetId;
    public int seasonId;
    public int roundId;
}