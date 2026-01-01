using System;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

/// <summary>
/// A cross-platform WebSocket wrapper using System.Net.WebSockets.ClientWebSocket
/// Works on both Windows (Unity Editor) and Linux builds
/// </summary>
public class NativeWebSocketWrapper : IDisposable
{
    private ClientWebSocket _ws;
    private CancellationTokenSource _cts;
    private readonly int _receiveBufferSize;
    
    public event Action OnOpen;
    public event Action<string> OnMessage;
    public event Action<string> OnError;
    public event Action<ushort, string> OnClose;
    
    public bool IsConnected => _ws?.State == WebSocketState.Open;
    
    public NativeWebSocketWrapper(int receiveBufferSize = 8192)
    {
        _receiveBufferSize = receiveBufferSize;
    }
    
    public async Task ConnectAsync(string url)
    {
        try
        {
            _ws = new ClientWebSocket();
            _cts = new CancellationTokenSource();
            
            Debug.Log($"[NativeWebSocket] Connecting to {url}");
            
            await _ws.ConnectAsync(new Uri(url), _cts.Token);
            
            Debug.Log("[NativeWebSocket] Connected!");
            OnOpen?.Invoke();
            
            // Start receiving messages
            _ = ReceiveLoopAsync();
        }
        catch (Exception ex)
        {
            Debug.LogError($"[NativeWebSocket] Connection failed: {ex.Message}");
            OnError?.Invoke(ex.Message);
            OnClose?.Invoke(1006, ex.Message);
        }
    }
    
    private async Task ReceiveLoopAsync()
    {
        var buffer = new byte[_receiveBufferSize];
        var messageBuffer = new StringBuilder();
        
        try
        {
            while (_ws.State == WebSocketState.Open && !_cts.Token.IsCancellationRequested)
            {
                var segment = new ArraySegment<byte>(buffer);
                WebSocketReceiveResult result;
                
                try
                {
                    result = await _ws.ReceiveAsync(segment, _cts.Token);
                }
                catch (OperationCanceledException)
                {
                    break;
                }
                
                if (result.MessageType == WebSocketMessageType.Close)
                {
                    await _ws.CloseAsync(WebSocketCloseStatus.NormalClosure, "Server closed", CancellationToken.None);
                    OnClose?.Invoke((ushort)(result.CloseStatus ?? WebSocketCloseStatus.NormalClosure), 
                                   result.CloseStatusDescription ?? "Connection closed");
                    break;
                }
                
                if (result.MessageType == WebSocketMessageType.Text)
                {
                    messageBuffer.Append(Encoding.UTF8.GetString(buffer, 0, result.Count));
                    
                    if (result.EndOfMessage)
                    {
                        var message = messageBuffer.ToString();
                        messageBuffer.Clear();
                        OnMessage?.Invoke(message);
                    }
                }
            }
        }
        catch (WebSocketException ex)
        {
            Debug.LogError($"[NativeWebSocket] WebSocket error: {ex.Message}");
            OnError?.Invoke(ex.Message);
            OnClose?.Invoke(1006, ex.Message);
        }
        catch (Exception ex)
        {
            Debug.LogError($"[NativeWebSocket] Receive error: {ex.Message}");
            OnError?.Invoke(ex.Message);
        }
    }
    
    public async Task SendAsync(string message)
    {
        if (_ws?.State != WebSocketState.Open)
        {
            Debug.LogWarning("[NativeWebSocket] Cannot send - not connected");
            return;
        }
        
        try
        {
            var bytes = Encoding.UTF8.GetBytes(message);
            var segment = new ArraySegment<byte>(bytes);
            await _ws.SendAsync(segment, WebSocketMessageType.Text, true, _cts.Token);
        }
        catch (Exception ex)
        {
            Debug.LogError($"[NativeWebSocket] Send error: {ex.Message}");
            OnError?.Invoke(ex.Message);
        }
    }
    
    public async Task CloseAsync()
    {
        if (_ws == null) return;
        
        try
        {
            _cts?.Cancel();
            
            if (_ws.State == WebSocketState.Open)
            {
                await _ws.CloseAsync(WebSocketCloseStatus.NormalClosure, "Client closing", CancellationToken.None);
            }
        }
        catch (Exception ex)
        {
            Debug.LogWarning($"[NativeWebSocket] Close error: {ex.Message}");
        }
    }
    
    public void Dispose()
    {
        _cts?.Cancel();
        _cts?.Dispose();
        _ws?.Dispose();
    }
}
