"""
Debugging Script for Immediate Job Assignment.
Does NOT require full Unity client. Simulates WebSocket connection.
"""
import ssl
import json
import time
import uuid
import websocket
import threading

SERVER_URL = "ws://127.0.0.1:8000/ws/server/"

def run_fake_server(server_id):
    ws_url = f"{SERVER_URL}{server_id}/"
    print(f"[{server_id}] Connecting to {ws_url}...")
    
    def on_message(ws, message):
        data = json.loads(message)
        print(f"\n[{server_id}] 📩 RECEIVED: {data['type']}")
        
        if data['type'] == 'assign_job':
            print(f"[{server_id}] ✅ JOB ASSIGNED! Map: {data['map_id']}")
            
            # Simulate processing time (short)
            time.sleep(1)
            
            # Send results
            result = {
                "type": "job_done",
                "map_id": data['map_id'],
                "result": {"score": 100},
                "next_round_time": None # Should be optional now? No wait, orchestrator calculates it? 
                # Wait, consumer expects next_round_time in job_done message?
                # Let's check consumer.py: handle_job_done expects next_round_time
            }
            # For test, just send a future time
            from datetime import datetime, timedelta
            future_time = (datetime.now() + timedelta(minutes=1)).isoformat()
            result['next_round_time'] = future_time
            
            ws.send(json.dumps(result))
            print(f"[{server_id}] 📤 Sent job_done for {data['map_id']}")

    def on_error(ws, error):
        print(f"[{server_id}] ❌ Error: {error}")

    def on_close(ws, close_status_code, close_msg):
        print(f"[{server_id}] Closed")

    def on_open(ws):
        print(f"[{server_id}] Connected! Sending heartbeat...")
        # Send heartbeat to register
        ws.send(json.dumps({
            "type": "heartbeat",
            "idle_cpu": 10,
            "idle_ram": 20
        }))
        # Send status update = idle
        ws.send(json.dumps({
            "type": "status_update",
            "status": "idle"
        }))

    ws = websocket.WebSocketApp(ws_url,
                              on_open=on_open,
                              on_message=on_message,
                              on_error=on_error,
                              on_close=on_close)
    
    ws.run_forever()

if __name__ == "__main__":
    # 1. Create a map via API (to ensure queue has something)
    import requests
    try:
        map_id = f"debug_map_{int(time.time())}"
        print(f"Creating map {map_id}...")
        resp = requests.post("http://127.0.0.1:8000/api/map/create/", json={
            "map_id": map_id,
            "season_id": 1
        })
        print(f"Map create response: {resp.status_code}")
    except Exception as e:
        print(f"Map create failed: {e}")
        exit(1)

    print("Waiting 2 seconds...")
    time.sleep(2)
    
    # 2. Connect a fake server - SHOULD receive job IMMEDIATELY
    server_id = f"unity_debug_{int(time.time())}"
    t = threading.Thread(target=run_fake_server, args=(server_id,))
    t.start()
    
    time.sleep(10)
    print("Test finished (timeout)")
