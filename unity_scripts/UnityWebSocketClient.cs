using UnityEngine;
using WebSocketSharp;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using System.Collections;
using UnityEngine.Networking;
using System.Text;

public class UnityWebSocketClient : MonoBehaviour
{
    public string backendUrl = "ws://localhost:8000/ws/server/";
    public string apiUrl = "http://localhost:8000/api/";
    public string serverId = "server01";
    
    private WebSocket ws;

    void Start()
    {
        Connect();
        StartCoroutine(SendHeartbeatRoutine());
    }

    void Connect()
    {
        string url = backendUrl + serverId + "/";
        ws = new WebSocket(url);

        ws.OnOpen += (sender, e) =>
        {
            Debug.Log("WebSocket Connected");
        };

        ws.OnMessage += (sender, e) =>
        {
            Debug.Log("Message Received: " + e.Data);
            HandleMessage(e.Data);
        };

        ws.OnClose += (sender, e) =>
        {
            Debug.Log("WebSocket Closed: " + e.Reason);
        };

        ws.OnError += (sender, e) =>
        {
            Debug.LogError("WebSocket Error: " + e.Message);
        };

        ws.Connect();
    }

    void HandleMessage(string jsonMessage)
    {
        try
        {
            var data = JObject.Parse(jsonMessage);
            string type = (string)data["type"];
            string action = (string)data["action"];
            JObject payload = (JObject)data["payload"];

            if (type == "command")
            {
                switch (action)
                {
                    case "assign_job":
                        int mapId = (int)payload["mapId"];
                        Debug.Log("Job Assigned: Map " + mapId);
                        StartCoroutine(ProcessJob(mapId));
                        break;
                    case "ping":
                        SendStatus("pong", new JObject());
                        break;
                    default:
                        Debug.LogWarning("Unknown command: " + action);
                        break;
                }
            }
        }
        catch (System.Exception ex)
        {
            Debug.LogError("Error parsing message: " + ex.Message);
        }
    }

    IEnumerator ProcessJob(int mapId)
    {
        // 1. GET Map Data
        string getUrl = apiUrl + "map/" + mapId + "/";
        using (UnityWebRequest webRequest = UnityWebRequest.Get(getUrl))
        {
            yield return webRequest.SendWebRequest();

            if (webRequest.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError("Error fetching map data: " + webRequest.error);
                yield break;
            }
            
            Debug.Log("Map Data Received: " + webRequest.downloadHandler.text);
            // Parse map data if needed
        }

        // 2. Simulate Calculation
        yield return new WaitForSeconds(3f); 
        
        // 3. Calculate Result (Next Run Time)
        long nextRun = System.DateTimeOffset.UtcNow.ToUnixTimeSeconds() + 10;
        
        // 4. POST Result
        var resultData = new JObject();
        resultData["mapId"] = mapId;
        resultData["seasonId"] = 1; // Example
        resultData["roundId"] = 2; // Example
        resultData["nextTime"] = System.DateTime.UtcNow.AddSeconds(10).ToString("o"); // ISO 8601

        string postUrl = apiUrl + "result/";
        var request = new UnityWebRequest(postUrl, "POST");
        byte[] bodyRaw = Encoding.UTF8.GetBytes(resultData.ToString());
        request.uploadHandler = new UploadHandlerRaw(bodyRaw);
        request.downloadHandler = new DownloadHandlerBuffer();
        request.SetRequestHeader("Content-Type", "application/json");

        yield return request.SendWebRequest();

        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError("Error posting result: " + request.error);
        }
        else
        {
            Debug.Log("Result Posted Successfully");
            
            // 5. Send WebSocket Event
            var eventPayload = new JObject();
            eventPayload["mapId"] = mapId;
            eventPayload["status"] = "done";
            SendEvent("job_done", eventPayload);
        }
    }

    IEnumerator SendHeartbeatRoutine()
    {
        while (true)
        {
            if (ws != null && ws.IsAlive)
            {
                var payload = new JObject();
                payload["cpu"] = Random.Range(10, 50); 
                payload["players"] = 0; 

                SendStatus("heartbeat", payload);
            }
            yield return new WaitForSeconds(5f);
        }
    }

    void SendStatus(string action, JObject payload)
    {
        var message = new JObject();
        message["type"] = "status";
        message["action"] = action;
        message["serverId"] = serverId;
        message["payload"] = payload;

        ws.Send(message.ToString());
    }
    
    void SendEvent(string action, JObject payload)
    {
        var message = new JObject();
        message["type"] = "event";
        message["action"] = action;
        message["serverId"] = serverId;
        message["payload"] = payload;

        ws.Send(message.ToString());
    }

    void OnDestroy()
    {
        if (ws != null)
        {
            ws.Close();
        }
    }
}
