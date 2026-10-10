from arduino.app_bricks.web_ui import WebUI

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


ui.on_message('senha', verificar_senha)
ui.on_message('area_marcada', calcular_area)
ui.on_message("limpar_box_risco", limpar_box_risco)
ui.on_message('retornar_box_risco', lambda *args : ui.send_message("box_risco", box_risco))