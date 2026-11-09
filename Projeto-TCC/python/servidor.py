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

def enviar_telemetria(operarios):
    global _ui_telemetria_ultimo
    agora = time.time()
    if agora - _ui_telemetria_ultimo < 0.2:
        return  # controle de taxa: min 0.2s entre envios
    _ui_telemetria_ultimo = agora
    ui.send_message("telemetria_gemeo", {"operarios": operarios})

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
