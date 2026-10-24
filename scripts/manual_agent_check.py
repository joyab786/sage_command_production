import os
import sys
import asyncio
import websockets
import json

# Local development requires explicit SAGE_ENV=development for dev authentication and mock tokens
os.environ.setdefault("SAGE_ENV", "development")

async def test_agent(message="What tables are in the database? List them."):
    # Use dev token parameter for local development WebSocket handshake
    uri = "ws://127.0.0.1:8000/ws/sage?token=manager_token"
    print(f"\n Connecting to SageCommand agent...")
    print(f" Sending: {message}\n")

    async with websockets.connect(uri) as ws:
        payload = json.dumps({"command": "chat", "text": message})
        await ws.send(payload)

        for _ in range(10):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
                data = json.loads(raw)
                msg_type = data.get("type", "unknown")

                if msg_type == "node_update":
                    print(f"[NODE]  >> {data.get('node')}")
                elif msg_type == "chat_response":
                    print(f"[AGENT REPLY]\n{data.get('text')}")
                    break
                elif msg_type == "log":
                    print(f"[LOG]   {data.get('message')}")
                else:
                    print(f"[{msg_type}] {data}")
            except asyncio.TimeoutError:
                print("[TIMEOUT] No response in 30s")
                break

if __name__ == "__main__":
    asyncio.run(test_agent())
