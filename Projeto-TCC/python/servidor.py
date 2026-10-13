"""Estado e mensagens da WebUI do detector de EPIs.

O retângulo ``box_risco`` é a mesma referência geométrica usada pelo
detector do Lucas. A integração observacional apenas consome o veredicto já
calculado pelo detector; ela não reinterpreta esta área neste módulo.
"""
from arduino.app_bricks.web_ui import WebUI

import banco

box_risco = None
senha_acesso = 937389
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


def verificar_senha(cliente, data):
    senha = data.get("senha")
    if senha == senha_acesso:
        ui.send_message("liberado", {}, room=cliente)
    else:
        ui.send_message("rejeitado", {}, room=cliente)


def enviar_log(mensagem):
    """Preserva o log em tempo real exibido na interface original."""
    ui.send_message("log_deteccao", mensagem)


ui.on_message("senha", verificar_senha)
ui.on_message("area_marcada", calcular_area)
ui.on_message("limpar_box_risco", limpar_box_risco)
ui.on_message(
    "retornar_box_risco",
    lambda *args: ui.send_message("box_risco", box_risco),
)

# Endpoints HTTP que alimentam o painel analítico e a galeria de infrações.
ui.expose_api("GET", "/foto/{nome_foto}", banco.pegar_foto)
ui.expose_api("GET", "/listar_ocorrencias", banco.dados_ocorrencias)
ui.expose_api("GET", "/dashboard_dados", banco.dados_dashboard)