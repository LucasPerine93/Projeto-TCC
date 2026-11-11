import time
from fastapi import Request
from arduino.app_bricks.web_ui import WebUI
import banco
import seguranca

box_risco = None
risco = False

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
