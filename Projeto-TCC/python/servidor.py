import time
import os
import json
from fastapi import Request
from fastapi.responses import Response, FileResponse
from arduino.app_bricks.web_ui import WebUI
import banco
import seguranca

box_risco = None
risco = False

# ---------------------------------------------------------------------------
# Buffer do último frame capturado pela câmera (para /snapshot)
# ---------------------------------------------------------------------------
_ultimo_frame_jpeg = None  # bytes JPEG do frame mais recente

# Caminho do arquivo de persistência da calibração do Gêmeo 3D
CALIBRACAO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibracao_gemeo.json")


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


ui = WebUI()

def calcular_area(_, data):
    global box_risco, risco
    box_risco = [data["x1"], data["y1"], data["x2"], data["y2"]]
    risco = True

def limpar_box_risco(*args):
    global box_risco, risco
    box_risco = None
    risco = False

def enviar_log(mensagem):
    ui.send_message("log_deteccao", mensagem)

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

        workers.append({
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
        })

    ui.send_message("telemetria_gemeo", {
        "source": "real",
        "timestamp": int(agora * 1000),
        "sequence": _telemetria_sequencia,
        "frame": {"w": 720, "h": 480},
        "workers": workers,
    })
    return True

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


ui.expose_api("GET", "/calibracao", _get_calibracao)
ui.expose_api("POST", "/calibracao", _post_calibracao)
