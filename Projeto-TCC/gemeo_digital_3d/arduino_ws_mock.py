"""Servidor WebSocket de teste para o Gêmeo Digital 3D v7.0.

Simula a telemetria que o Arduino UNO Q enviaria. Uso:
    pip install websockets
    python3 arduino_ws_mock.py          # escuta em ws://localhost:8000/ws
    python3 arduino_ws_mock.py 5000     # ou em ws://localhost:5000/ws

Formato enviado (x e z em metros; planta de 40 x 30 m com origem no centro):
    { "id": "OP-01", "x": -6.2, "z": 3.4, "capacete": true, "colete": true, "inRisk": false }
"""
import asyncio, json, math, sys, time
import websockets

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

async def handler(ws):
    t0 = time.time()
    while True:
        t = time.time() - t0
        msgs = [
            {"id": "OP-01", "x": -8 + 5 * math.cos(t * 0.5), "z": 4 + 3 * math.sin(t * 0.5),
             "capacete": True, "colete": True, "inRisk": False},
            {"id": "OP-02", "x": 6 + 4 * math.cos(t * 0.4 + 1), "z": -5 + 3 * math.sin(t * 0.4 + 1),
             "capacete": int(t) % 12 < 6, "colete": True, "inRisk": False},   # alterna o capacete a cada 6 s
        ]
        for m in msgs:
            await ws.send(json.dumps(m))
        await asyncio.sleep(0.1)

async def main():
    async with websockets.serve(handler, "localhost", PORT):
        print(f"Servidor de teste em ws://localhost:{PORT}/ws (Ctrl+C para parar)")
        await asyncio.Future()

asyncio.run(main())
