using UnityEngine;
using WebSocketSharp;
using Newtonsoft.Json.Linq;
using System.Collections;
using UnityEngine.Networking;
using System;
using System.Threading.Tasks;

[RequireComponent(typeof(PerformanceTracker))]
public class UnityWebSocketClient : MonoBehaviour
{
    // private string backendWsUrl = "ws://103.12.214.244/ws/server/";
    private string backendWsUrl = "ws://127.0.0.1:8000/ws/server/";


    [Header("Server Identity")] public string serverId;

    private WebSocket ws;
    private string publicIP = "";

    private float heartbeatTime = 5f;
    private WaitForSeconds heartbeatWait;

    public bool IsInitialized { get; private set; }
    public PerformanceTracker performanceTracker;

    // ===============================
    // RECONNECT STATE
    // ===============================
    private int reconnectAttempt;
    private Coroutine reconnectRoutine;
    private bool isQuitting;
    private bool isReconnecting; // Track if this is a reconnection vs initial connect

    private enum DisconnectReason
    {
        None,
        ManualQuit,
        ServerClosed,
        NetworkError,
        Unknown
    }

    private DisconnectReason lastDisconnectReason = DisconnectReason.None;

    // ===============================
    // UNITY LIFECYCLE
    // ===============================

    private void Awake()
    {
        heartbeatTime = Mathf.Max(heartbeatTime, 1f);
        heartbeatWait = new WaitForSeconds(heartbeatTime);

        if (performanceTracker == null)
            performanceTracker = GetComponent<PerformanceTracker>();
    }


    public IEnumerator InitializeAndConnect()
    {
        yield return StartCoroutine(GetPublicIP());
        serverId = $"unity_{publicIP.Replace(".", "_")}";

        Connect();
        StartCoroutine(SendHeartbeat());

        // Wait for connection
        yield return new WaitUntil(() => IsInitialized);

        // Backend already marked as 'not_initialized'
        Debug.Log("[Init] Server connected, initializing systems...");

        // Do your initialization (load assets, etc.)
        yield return StartCoroutine(InitializeGameSystems());

        // NOW mark as idle - ready for jobs!
        SendStatusUpdate("idle");
        Debug.Log("[Init] ✅ Server ready to receive jobs");
    }

    private IEnumerator InitializeGameSystems()
    {
        // Your initialization logic here
        yield return new WaitUntil(() => PinoWorldManager.Instance.IsSystemReady);
    }


    // ===============================
    // GET PUBLIC IP
    // ===============================

    private IEnumerator GetPublicIP()
    {
        Debug.Log("[IP] 🌐 Fetching public IP...");

        string[] services =
        {
            "https://api.ipify.org?format=text",
            "https://checkip.amazonaws.com"
        };

        foreach (var url in services)
        {
            using UnityWebRequest request = UnityWebRequest.Get(url);
            request.timeout = 5; // 🔒 important for servers

            yield return request.SendWebRequest();

            if (request.result == UnityWebRequest.Result.Success)
            {
                publicIP = request.downloadHandler.text.Trim();

                if (!string.IsNullOrEmpty(publicIP))
                {
                    Debug.Log($"[IP] ✅ Public IP detected: {publicIP}");
                    yield break;
                }
            }
            else
            {
                Debug.LogWarning($"[IP] ⚠️ Failed from {url}: {request.error}");
            }
        }

        // If all services fail
        publicIP = "unknown";
        Debug.LogError("[IP] ❌ Could not determine public IP, using 'unknown'");
    }


    // ===============================
    // WEBSOCKET
    // ===============================

    private void Connect()
    {
        string wsUrl = $"{backendWsUrl}{serverId}/";

        ws = new WebSocket(wsUrl);
        Debug.Log($"[WebSocket] 🔌 Connecting → {wsUrl}");

        ws.OnOpen += (s, e) =>
        {
            IsInitialized = true;
            reconnectAttempt = 0;
            lastDisconnectReason = DisconnectReason.None;

            Debug.Log($"[WebSocket] ✅ Connected as {serverId}");

            // On reconnect, immediately send idle status to let Django know we're ready
            if (isReconnecting)
            {
                MainThreadDispatcher.Enqueue(() =>
                {
                    SendStatusUpdate("idle");
                    Debug.Log("[WebSocket] ✅ Reconnected and marked as idle");
                });
                isReconnecting = false;
            }
        };

        ws.OnMessage += (s, e) => { MainThreadDispatcher.Enqueue(() => { HandleMessage(e.Data); }); };

        ws.OnError += (s, e) => { Debug.LogError($"[WebSocket] ❌ Error: {e.Message}"); };

        ws.OnClose += (s, e) =>
        {
            IsInitialized = false;

            lastDisconnectReason = e.Code switch
            {
                1000 => DisconnectReason.ManualQuit,
                1001 => DisconnectReason.ServerClosed,
                1006 => DisconnectReason.NetworkError,
                _ => DisconnectReason.Unknown
            };

            Debug.LogWarning(
                $"[WebSocket] ❌ Disconnected | Code={e.Code}, Reason={e.Reason}, Type={lastDisconnectReason}"
            );

            if (!isQuitting)
                ScheduleReconnect();
        };

        ws.Connect();
    }

    // ===============================
    // RECONNECT LOGIC
    // ===============================

    private void ScheduleReconnect()
    {
        if (reconnectRoutine != null)
            StopCoroutine(reconnectRoutine);

        reconnectRoutine = StartCoroutine(ReconnectRoutine());
    }

    private IEnumerator ReconnectRoutine()
    {
        reconnectAttempt++;
        float delay = Mathf.Min(5f * reconnectAttempt, 30f);

        Debug.Log($"[WebSocket] 🔄 Reconnect attempt {reconnectAttempt} in {delay}s");
        yield return new WaitForSeconds(delay);

        if (isQuitting) yield break;

        Debug.Log("[WebSocket] 🔁 Reconnecting...");
        isReconnecting = true; // Mark as reconnection attempt
        try
        {
            ws?.Close();
            Connect();
        }
        catch (Exception ex)
        {
            Debug.LogError($"[WebSocket] ❌ Reconnect failed: {ex.Message}");
            isReconnecting = false;
            ScheduleReconnect();
        }
    }

    // ===============================
    // MESSAGE HANDLING
    // ===============================

    private void HandleMessage(string message)
    {
        try
        {
            JObject data = JObject.Parse(message);
            string type = data["type"]?.ToString();
            switch (type)
            {
                case "assign_job":
                    HandleJob(data);
                    break;

                case "command":
                    HandleCommand(data);
                    break;
                case "pong":
                    Debug.Log("Server returned PONG");
                    break;

                default:
                    Debug.LogWarning($"[WebSocket] Unknown message type: {type}");
                    break;
            }
        }
        catch (Exception ex)
        {
            Debug.LogError($"[WebSocket] Parse error: {ex.Message}");
        }
    }

    private void HandleJob(JObject data)
    {
        // Mark as busy immediately when receiving job
        SendStatusUpdate("busy");

        PlanetCalculateOrder order = new PlanetCalculateOrder
        {
            planetId = data["planet_id"]?.ToObject<int>() ?? 0,
            seasonId = data["season_id"]?.ToObject<int>() ?? 0,
            roundId = data["round_id"]?.ToObject<int>() ?? 0
        };

        if (order.planetId <= 0)
        {
            Debug.LogError("[Job] Invalid planetId");
            SendStatusUpdate("idle"); // Revert to idle if invalid
            return;
        }

        Debug.Log($"[Job] 📋 Assigned planet {order.planetId}");

        MainThreadDispatcher.Enqueue(async () =>
        {
            try
            {
                await PinoWorldManager.Instance.OnPlanetCalculateOrderReceive(order);
            }
            catch (Exception ex)
            {
                Debug.LogException(ex);
                SendFailed(order.planetId, ex.Message);
            }
        });
    }

    private void HandleCommand(JObject data)
    {
        string command = data["command"]?.ToString();
        Debug.Log($"[Command] {command}");

        if (command == "stop_server")
        {
            // Application.Quit();
        }
        else if (command == "reboot_server")
        {
            // Application.Quit();
        }
    }

    // ===============================
    // HEARTBEAT
    // ===============================

    private IEnumerator SendHeartbeat()
    {
        while (Application.isPlaying)
        {
            yield return heartbeatWait;

            if (ws != null && ws.IsAlive)
            {
                try
                {
                    JObject msg = new JObject
                    {
                        ["type"] = "heartbeat",
                        ["idle_cpu"] = performanceTracker.idlePeakCPU,
                        ["max_cpu"] = performanceTracker.taskPeakCPU,
                        ["idle_ram"] = performanceTracker.idlePeakRAM,
                        ["max_ram"] = performanceTracker.taskPeakRAM,
                        ["disk"] = performanceTracker.currentDisk
                    };

                    ws.Send(msg.ToString());
                }
                catch (Exception ex)
                {
                    Debug.LogWarning($"[Heartbeat] Error: {ex.Message}");
                }
            }
        }
    }

    // ===============================
    // OUTGOING MESSAGES
    // ===============================

    public void SendStatusUpdate(string status)
    {
        if (ws == null || !ws.IsAlive) return;

        ws.Send(new JObject
        {
            ["type"] = "status_update",
            ["status"] = status
        }.ToString());
    }

    public void SendJobDone(JobDoneInfo info)
    {
        if (ws == null || !ws.IsAlive) return;

        // Parse the datetime string as UTC
        DateTime nextRoundTime = DateTime.ParseExact(
            info.nextRoundTimeStr, "yyyy-MM-dd HH:mm:ss",
            System.Globalization.CultureInfo.InvariantCulture,
            System.Globalization.DateTimeStyles.AssumeUniversal |
            System.Globalization.DateTimeStyles.AdjustToUniversal
        );

        ws.Send(new JObject
        {
            ["type"] = "job_done",
            ["planet_id"] = info.planetId.ToString(),
            ["season_id"] = info.seasonId.ToString(),
            ["round_number"] = info.currentRoundNumber.ToString(),
            ["round_id"] = info.roundId.ToString(),
            ["next_round_time"] = nextRoundTime.ToString("O") // ISO 8601 format with Z suffix
        }.ToString());

        Debug.Log($"[Job Done] ✅ Sent for {info.planetId}, next: {nextRoundTime:O}");

        // Mark server as idle for new assignments
        SendStatusUpdate("idle");
    }

    public void SendFailed(int planetId, string cause)
    {
        if (ws == null || !ws.IsAlive) return;

        ws.Send(new JObject
        {
            ["type"] = "error",
            ["planet_id"] = planetId.ToString(),
            ["error"] = cause
        }.ToString());

        // Mark server as idle after error
        SendStatusUpdate("idle");
    }

    // ===============================
    // CLEANUP
    // ===============================

    private void SendDisconnect()
    {
        if (ws == null || !ws.IsAlive) return;

        Debug.Log("[WebSocket] 📤 Sending graceful disconnect");

        ws.Send(new JObject
        {
            ["type"] = "disconnect",
            ["server_id"] = serverId
        }.ToString());
    }

    private void OnApplicationQuit()
    {
        isQuitting = true;
        lastDisconnectReason = DisconnectReason.ManualQuit;
        SendDisconnect();
        ws?.Close();
    }

    private void OnDestroy()
    {
        isQuitting = true;
        ws?.Close();
    }
}

// ===============================
// DATA MODEL
// ===============================

public class PlanetCalculateOrder
{
    public int planetId;
    public int seasonId;
    public int roundId;
}

public class JobDoneInfo
{
    public int planetId;
    public int seasonId;
    public int roundId;
    public int currentRoundNumber;
    public string nextRoundTimeStr;
}