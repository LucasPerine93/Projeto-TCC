"""servidor.py — Rotas HTTP/WebSocket, WebUI e telemetria do gêmeo 3D.

Papel do arquivo
----------------
Sobe a interface web do painel no Arduino App Lab (``WebUI``/FastAPI),
persiste e expõe a calibração do gêmeo, guarda o último frame da câmera em
memória (``/snapshot``) e emite a telemetria de EPIs para o frontend em no
máximo ~5 Hz (``telemetria_gemeo``) — além de registrar as rotas REST de
segurança, painel, ocorrências, trajetória, mapa de calor e assistente.

Entradas / Saídas
-----------------
- Entrada: mensagens do frontend (``ui.on_message``), requisições HTTP
  (``ui.expose_api``) e chamadas internas do detector (``enviar_telemetria``).
- Saída: respostas JSON/JPEG e mensagens WebSocket com o estado do canteiro.

Índice de seções
----------------
1. Estado global, WebUI e rate-limit de telemetria (``enviar_telemetria`` 5 Hz)
2. Captura de ``/snapshot`` e persistência de ``/calibracao`` (helpers)
3. Rotas REST: autenticação, painel, ocorrências, trajetória, mapa de calor
   e assistente (registradas nos ``ui.on_message``/``ui.expose_api``)

``box_risco``/``risco`` e ``_ultimo_frame_jpeg`` são estado compartilhado
entre o detector (câmera) e o frontend — por isso são globais do módulo.
"""
import time
import os
import json
from fastapi import Request
from fastapi.responses import Response, FileResponse
from arduino.app_bricks.web_ui import WebUI
import banco
import assistente
import seguranca

# ===== 1. ESTADO GLOBAL, WEBUI E RATE-LIMIT DE TELEMETRIA =====
# Estado compartilhado com o detector.py (câmera marca a área; aqui ela é
# lida para devolver a moldura ao frontend quando pedido).
box_risco = None
risco = False

# Caminho do arquivo de persistência da calibração do Gêmeo 3D
CALIBRACAO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibracao_gemeo.json")

# Instância única do servidor Web (rotas e WebSocket registradas no fim).
ui = WebUI()


def calcular_area(_, data):
    """Frontend marca o perímetro da área de risco com o mouse (mensagem area_marcada)."""
    global box_risco, risco
    box_risco = [data["x1"], data["y1"], data["x2"], data["y2"]]
    risco = True

def limpar_box_risco(*args):
    """Apaga a moldura da área de risco (mensagem limpar_box_risco)."""
    global box_risco, risco
    box_risco = None
    risco = False

def enviar_log(mensagem):
    """Encaminha uma linha de log do detector para o console do painel (log_deteccao)."""
    ui.send_message("log_deteccao", mensagem)

# Rate-limit de telemetria: no máximo um quadro a cada 0,2 s (~5 Hz), com
# ``sequence`` crescente para o frontend detectar perdas de pacote.
_ui_telemetria_ultimo = 0.0
_telemetria_sequencia = 0

def enviar_telemetria(operarios):
    """Envia um quadro de telemetria do Gêmeo 3D em no máximo ~5 Hz.

    ``track_id`` é uma trilha efêmera, não uma identidade civil. Quadros vazios
    são enviados quando permitido pelo limite de taxa para que o cliente saiba
    que a fonte real permanece ativa mesmo sem pessoas na câmera.
    """
    global _ui_telemetria_ultimo, _telemetria_sequencia

    agora = time.time()
    if agora - _ui_telemetria_ultimo < 0.2:
        return False

    _ui_telemetria_ultimo = agora
    _telemetria_sequencia += 1
    workers = []

    for operario in operarios:
        if operario.track_id is None:
            continue

        dados = {
            "id": str(operario.track_id),
            "bbox": list(operario.box_xyxy),
            "ppe": {
                "helmet": bool(operario.tem_capacete),
                "vest": bool(operario.tem_colete),
            },
            "confidence": {
                "person": operario.conf_pessoa,
                "helmet": operario.conf_capacete,
                "vest": operario.conf_colete,
            },
            "inRisk": bool(operario.risco_detectado),
        }
        # Posição na planta (metros, origem no centro) — Etapa 3: só quando há calibração
        if getattr(operario, "pos_x_m", None) is not None and getattr(operario, "pos_z_m", None) is not None:
            dados["position"] = {"x": operario.pos_x_m, "z": operario.pos_z_m}
        workers.append(dados)

    ui.send_message("telemetria_gemeo", {
        "source": "real",
        "timestamp": int(agora * 1000),
        "sequence": _telemetria_sequencia,
        "frame": {"w": 720, "h": 480},
        "workers": workers,
    })
    return True


# ===== 2. CAPTURA DE /snapshot E PERSISTÊNCIA DE /calibracao =====
# Helpers compartilhados pela rota /snapshot e pelo calibrador do gêmeo.
# ``/snapshot`` devolve o último frame JPEG da câmera; se não houver câmera
# (lib antiga/ambiente de teste), cai numa foto de evidência e por fim num
# frame padrão com grade de calibração.
_ultimo_frame_jpeg = None  # bytes JPEG do frame mais recente


def atualizar_ultimo_frame(jpeg_bytes):
    """Guarda em memória os bytes JPEG do frame mais recente capturado pela câmera."""
    global _ultimo_frame_jpeg
    _ultimo_frame_jpeg = jpeg_bytes


def _ultima_foto_ocorrencia():
    """Retorna o caminho da foto .jpg mais recente na pasta de ocorrências, se existir."""
    try:
        fotos = []
        for nome in os.listdir(banco.PASTA_FOTOS):
            if nome.lower().endswith((".jpg", ".jpeg")):
                fotos.append(os.path.join(banco.PASTA_FOTOS, nome))
        if fotos:
            fotos.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            return fotos[0]
    except (FileNotFoundError, OSError):
        pass
    return None


def _frame_padrao_jpeg():
    """Gera um frame padrão 720x480 com grade de calibração (ambiente de teste sem câmera)."""
    try:
        import io
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            # Fallback: SVG simples convertido para bytes (não é JPEG mas o navegador exibe)
            svg = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="480">'
                '<rect width="720" height="480" fill="#1a1a1a"/>'
                '<text x="360" y="240" font-family="monospace" font-size="24" fill="#888" text-anchor="middle">'
                'FRAME PADRÃO 720×480 – sem câmera ao vivo</text>'
                '</svg>'
            )
            return svg.encode("utf-8"), "image/svg+xml"
        img = Image.new("RGB", (720, 480), (26, 26, 26))
        d = ImageDraw.Draw(img)
        # Grade de calibração
        for x in range(0, 720, 80):
            d.line([(x, 0), (x, 479)], fill=(60, 60, 60), width=1)
        for y in range(0, 480, 60):
            d.line([(0, y), (719, y)], fill=(60, 60, 60), width=1)
        d.text((360, 240), "FRAME PADRÃO 720×480\nsem câmera ao vivo", fill=(160, 160, 160), anchor="mm")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        # Último recurso: PNG 1x1 transparente
        return b"", "image/jpeg"


def _ler_calibracao():
    """Lê a calibração persistida em disco (calibracao_gemeo.json)."""
    try:
        with open(CALIBRACAO_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _salvar_calibracao(dados):
    """Persiste a calibração em disco (calibracao_gemeo.json)."""
    try:
        dados = dict(dados)
        dados["updatedAt"] = int(time.time() * 1000)
        with open(CALIBRACAO_PATH, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


# ===== 3. ROTAS REST — AUTENTICAÇÃO, PAINEL, OCORRÊNCIAS, TRAJETÓRIA, CALOR E ASSISTENTE =====
# Mensagens em tempo real (WebSocket/ui.on_message)...
ui.on_message('area_marcada', calcular_area)
ui.on_message("limpar_box_risco", limpar_box_risco)
ui.on_message('retornar_box_risco', lambda *args : ui.send_message("box_risco", box_risco))

# Rotas de segurança HTTP expostas via WebUI / FastAPI
ui.expose_api("POST", "/login", seguranca.login)
ui.expose_api("GET", "/sessao", seguranca.sessao)
ui.expose_api("POST", "/logout", seguranca.logout)

# Rotas protegidas existentes
ui.expose_api("GET", "/foto/{nome_foto}", banco.pegar_foto)
ui.expose_api("GET", "/listar_ocorrencias", banco.dados_ocorrencias)
ui.expose_api("GET", "/dashboard_dados", banco.calcular_dados_dashboard)
# Revisão do técnico: nada é apagado (status/motivo/revisado_em)
ui.expose_api("POST", "/revisar_ocorrencia/{ocorrencia_id}", banco.revisar_ocorrencia)
ui.expose_api("POST", "/excluir_ocorrencia/{ocorrencia_id}", banco.excluir_ocorrencia)


# Snapshot do frame real da camera (Secao 7 do Plano de Evolucao)
def _snapshot(req):
    """GET /snapshot - retorna o frame mais recente da camera ou fallback."""
    if _ultimo_frame_jpeg:
        return Response(content=_ultimo_frame_jpeg, media_type="image/jpeg",
                        headers={"X-Snapshot-Source": "camera-live"})
    caminho = _ultima_foto_ocorrencia()
    if caminho:
        return FileResponse(caminho, media_type="image/jpeg",
                            headers={"X-Snapshot-Source": "ultima-ocorrencia"})
    conteudo, mtype = _frame_padrao_jpeg()
    return Response(content=conteudo, media_type=mtype,
                    headers={"X-Snapshot-Source": "padrao-teste"})


ui.expose_api("GET", "/snapshot", _snapshot)


# Persistencia da calibracao do Gemeo 3D (Secao 7 do Plano de Evolucao)
def _get_calibracao(req):
    """GET /calibracao - le a calibracao persistida em disco."""
    dados = _ler_calibracao()
    if dados is None:
        return {"erro": "calibracao nao encontrada"}, 404
    return dados


def _post_calibracao(req):
    """POST /calibracao - grava a calibracao enviada pelo frontend."""
    try:
        corpo = req.json() if hasattr(req, "json") else None
    except Exception:
        corpo = None
    if not corpo or not isinstance(corpo, dict):
        return {"erro": "corpo JSON invalido"}, 400
    campos_obrigatorios = ("camId", "H", "img", "world", "plan")
    for c in campos_obrigatorios:
        if c not in corpo:
            return {"erro": "campo obrigatorio ausente: " + c}, 400
    if _salvar_calibracao(corpo):
        return {"ok": True, "updatedAt": corpo.get("updatedAt")}
    return {"erro": "falha ao gravar calibracao"}, 500


# Rotas /calibracao — GET lê, POST grava (com os 5 campos obrigatórios).
ui.expose_api("GET", "/calibracao", _get_calibracao)
ui.expose_api("POST", "/calibracao", _post_calibracao)


# ---------------------------------------------------------------------------
# Etapas 4 e 5 do Plano de Evolucao: replay 3D de ocorrencias reais e mapa de calor
# ---------------------------------------------------------------------------
def _trajetoria_ocorrencia(ocorrencia_id):
    """GET /ocorrencia/{ocorrencia_id}/trajetoria — pontos para o replay 3D de uma ocorrencia."""
    try:
        ocorrencia_id = int(ocorrencia_id)
    except (TypeError, ValueError):
        return {"erro": "id de ocorrencia invalido"}, 400
    return {"ocorrencia_id": ocorrencia_id, "pontos": banco.obter_trajetoria(ocorrencia_id)}


def _mapa_calor(*_args):
    """GET /mapa_calor — mapa de calor historico com taxa de infracao por celula."""
    return {"celulas": banco.obter_mapa_calor()}


ui.expose_api("GET", "/ocorrencia/{ocorrencia_id}/trajetoria", _trajetoria_ocorrencia)
ui.expose_api("GET", "/mapa_calor", _mapa_calor)


# ---------------------------------------------------------------------------
# Etapa 8 do Plano de Evolucao: assistente contextual somente-leitura
# ---------------------------------------------------------------------------
async def _assistente(req: Request):
    """POST /assistente — pergunta ao assistente; consulta APENAS leitura do SQLite.

    Requer sessao do painel (cookie) + cabecalho x-requested-with: painel.
    Nao altera area de risco, regras de seguranca nem equipamentos: so responde
    com numeros ja gravados em banco.py (ocorrencias, conformidade e mapa).
    """
    negado = seguranca.exigir(req, escrita=True)
    if negado is not None:
        return negado
    try:
        corpo = await req.json()
    except Exception:
        corpo = None
    if not isinstance(corpo, dict):
        return {"erro": "corpo JSON invalido"}, 400
    pergunta = corpo.get("pergunta", "")
    if not isinstance(pergunta, str) or not pergunta.strip():
        return {"erro": "pergunta vazia"}, 400
    return assistente.responder(pergunta)


ui.expose_api("POST", "/assistente", _assistente)
