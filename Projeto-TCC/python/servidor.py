from arduino.app_bricks.web_ui import WebUI

box_risco = None
senha_acesso = 937389
risco = 0 # 1 é veradeiro | 0 é falso | a variavel começa como falsa

ui = WebUI()

def calcular_area(_, data):
    global box_risco
    box_risco = data.values()


def risco_ativo(_, data):
    global risco
    r = data
    risco = r

def verificar_senha(_, data):
    senha = data.get("senha")

    if senha == senha_acesso:
        ui.send_message("senha_processada", {"senha_processada": 0})

    else:
        ui.send_message("senha_processada", {"senha_processada": 1})
    

ui.on_message('senha', verificar_senha)
ui.on_message('area-marcada', calcular_area)
ui.on_message('risco', risco_ativo)