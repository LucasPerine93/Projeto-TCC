# Gêmeo Digital BIM 3D v7.0

Módulo isolado do Gêmeo Digital 3D para demonstração do TCC. Inclui planta 2D processável, extrusão BIM 3D, CFTV/PTZ, homografia, mapa de calor, replay 3D e telemetria de operários via WebSocket.

## Arquivos

- `index.html` — Command Center v7.0; funciona com Three.js local.
- `three.min.js` — Three.js r128 local, permitindo abrir o 3D sem depender da CDN.
- `arduino_ws_mock.py` — servidor de telemetria de teste compatível com o modo Arduino Live.

## Abrir o módulo

Use um servidor HTTP local a partir desta pasta. Exemplo com Python:

```powershell
cd Projeto-TCC/gemeo_digital_3d
python -m http.server 8030 --bind 127.0.0.1
```

Depois abra:

```text
http://127.0.0.1:8030/
```

> Evite abrir o HTML por `file://`, pois o navegador pode restringir recursos e WebSocket.

## Telemetria Arduino Live / WebSocket mock

Em outro terminal, na mesma pasta:

```powershell
python arduino_ws_mock.py
```

O mock escuta em:

```text
ws://localhost:8000/ws
```

No Command Center, selecione **Modo: Arduino Live (WS)**, mantenha a URL padrão e clique em **Conectar**.

## Formato JSON esperado do detector.py

O servidor/detector deve enviar uma mensagem JSON por operário, com coordenadas em metros e origem no centro da planta:

```json
{
  "id": "OP-01",
  "x": -6.2,
  "z": 3.4,
  "capacete": true,
  "colete": true,
  "inRisk": false
}
```

Campos:

| Campo | Tipo | Descrição |
| --- | --- | --- |
| `id` | string | Identificador do operário, por exemplo `OP-01` ou `OP-02`. |
| `x` | number | Posição X em metros. |
| `z` | number | Posição Z em metros. |
| `capacete` | boolean | Estado do capacete. |
| `colete` | boolean | Estado do colete. |
| `inRisk` | boolean | Indica se o operário está em área de risco. |

Também são aceitos um array de mensagens ou um objeto contendo `workers: [...]`.

## Recursos V7

- Three.js r128 offline (`three.min.js` local);
- mapa de calor e limpeza de histórico;
- CFTV com PTZ e pausas durante calibração;
- calibração de homografia em quatro pontos;
- replay 3D de trajetórias;
- modo Arduino Live via WebSocket;
- mock para testes sem hardware físico.
