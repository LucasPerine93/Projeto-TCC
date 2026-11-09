"""Servidor WebSocket de TESTE para o Gêmeo Digital 3D (dados FICTÍCIOS, só para desenvolvimento).

Serve para ver o modo "Dados reais" do gêmeo sem o Arduino. Ele não é o backend real:
o painel mostra "DADOS REAIS" porque a origem é a conexão, então use só em testes.

    pip install websockets
    python3 tools/ws_teste_gemeo.py          # ws://localhost:8000/ws
    python3 tools/ws_teste_gemeo.py 5000     # ou em outra porta

Envia o formato proposto em PLANO_EVOLUCAO.md (um quadro por mensagem, ~10 por segundo):
    { "source": "real", "timestamp": ms, "sequence": n,
      "workers": [{ "id", "position": {x, z}, "ppe": {helmet, vest},
                    "confidence": {person, helmet, vest}, "inRisk" }] }
x e z em metros (planta de 40 x 30 m, origem no centro). O terceiro trabalhador manda só a caixa na imagem
(formato nativo do detector), para testar o caso "sem posição na planta".
"""
import asyncio, json, math, sys, time
import websockets

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000


async def handler(ws):
    t0, seq = time.time(), 0
    while True:
        t = time.time() - t0
        seq += 1
        quadro = {
            "source": "real", "timestamp": int(time.time() * 1000), "sequence": seq,
            "workers": [
                {"id": "7", "position": {"x": -8 + 5 * math.cos(t * 0.5), "z": 4 + 3 * math.sin(t * 0.5)},
                 "ppe": {"helmet": True, "vest": True}, "confidence": {"person": 0.96, "helmet": 0.91, "vest": 0.88}},
                {"id": "12", "position": {"x": 6 + 4 * math.cos(t * 0.4 + 1), "z": -5 + 3 * math.sin(t * 0.4 + 1)},
                 "ppe": {"helmet": int(t) % 12 < 6, "vest": True}, "confidence": {"person": 0.93, "helmet": 0.74, "vest": 0.9}},
                {"track_id": 31, "box_xyxy": [120, 60, 220, 420], "tem_capacete": True, "tem_colete": True},
            ],
        }
        await ws.send(json.dumps(quadro))
        await asyncio.sleep(0.1)


async def main():
    async with websockets.serve(handler, "localhost", PORT):
        print(f"Servidor de teste em ws://localhost:{PORT}/ws (Ctrl+C para parar)")
        await asyncio.Future()

asyncio.run(main())
