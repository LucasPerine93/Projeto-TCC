from arduino.app_bricks.web_ui import WebUI

centro = None
width = None
height = None

senha_acesso = 937389

risco = 0 # 1 é veradeiro | 0 é falso | a variavel começa como falsa

ui = WebUI()

def calcular_area(_, data):
    global centro, width, height
    
    x1, y1, x2, y2 = data.get('pixels').values()
    centro = ((x1 + x2) / 2, (y1 + y2) / 2)

    width = x1 - x2
    height = y1 - y2

def calcular_risco(_, data):
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
ui.on_message('risco', calcular_risco)