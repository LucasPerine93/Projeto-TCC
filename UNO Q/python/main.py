from arduino.app_utils import App, Bridge
from arduino.app_bricks.video_objectdetection import VideoObjectDetection
from arduino.app_peripherals.camera import WebSocketCamera
from arduino.app_bricks.telegram_bot import TelegramBot, Sender
from arduino.app_bricks.web_ui import WebUI
from PIL import Image, ImageDraw

import io
import math

ID_chat = 8996760139
senha = 937389

servidor_bloqueado = 1 # 0 Bloqueado 1 Liberado
num_dispositivos = 0 # Dispositivos conectados

matrix = True # T: matrix é utilizada | F: matrix não é utilizado
ativar_envio = True # T: manda fotos | F: não manda fotos

bot = TelegramBot()
cam = WebSocketCamera(port=9393, resolution=(1440, 720), fps=12)

deteccao = VideoObjectDetection(
    cam, 
    confidence=0.6, 
    debounce_sec=0, 
    camera_preview=True,
)

ui = WebUI()

class Detectar:
    def __init__(self, camera_deteccao: str, limite_movimento):
        self.posicao_anterior = None
        self.camera_deteccao = camera_deteccao
        self.limite_movimento = limite_movimento
        
    def pessoa_detectada(self, specs_frame, frame=None):
        global matrix
            
        if frame is None:
            return
        try:
            x1, y1, x2, y2 = specs_frame.get('bounding_box_xyxy') # Pega as cordenadas x e y do retangulo
            
            centro_atual = ((x1 + x2) / 2, (y1 + y2) / 2) # Acha o centro do retangulo
    
            if self.posicao_anterior is not None:
                distancia = math.dist(centro_atual, self.posicao_anterior) # Calcula a distancia do centro atual para a distancia anterior
                if distancia < self.limite_movimento: # Se for menor que o limite de movimento não manda a imagem
                    return
    
            img = Image.open(io.BytesIO(frame)).convert('RGB')
            
            largura, altura = img.size
            meio_x = largura // 2

            if self.camera_deteccao == "camera 1":
                img_lado = img.crop((0, 0, meio_x, altura)) # Imagem esquerda
                cord_retangulo = [x1, y1, x2, y2]

            if self.camera_deteccao == "camera 2":
                img_lado = img.crop((meio_x, 0, largura, altura)) # Imagem direita
                cord_retangulo = [x1 - meio_x, y1, x2 - meio_x, y2]
            
            ImageDraw.Draw(img_lado).rectangle(cord_retangulo, outline="red", width=3)
    
            bytes_imagem_com_caixas = io.BytesIO()
            img_lado.save(bytes_imagem_com_caixas, format="JPEG")
            imagem_com_caixas = bytes_imagem_com_caixas.getvalue()
                
            bot.send_photo(ID_chat, imagem_com_caixas, f"Pessoa detectada na {self.camera_deteccao}")
    
            if matrix == True: 
                Bridge.call("pessoaDetectada")
    
            self.posicao_anterior = centro_atual
            
        except Exception as e:
            print(f"[ERRO]: {e}")

espiao1 = Detectar(camera_deteccao="camera 1", limite_movimento=55)
espiao2 = Detectar(camera_deteccao="camera 2", limite_movimento=40)

def callback_deteccao(specs_frame, frame=None):
    global ativar_envio
    
    if ativar_envio == True:
        
        if frame is None:
            return
            
        img_tamanho = Image.open(io.BytesIO(frame))
        largura, _ = img_tamanho.size

        img_metade = largura // 2
        
        x1, y2, x2, y2 = specs_frame.get("bounding_box_xyxy")
        centro = ((x1 + x2) / 2)

        if centro is not None:
            if centro < img_metade:
                espiao1.pessoa_detectada(specs_frame, frame)

            else:
                espiao2.pessoa_detectada(specs_frame, frame)
            

def esconder_matrix(Sender, _):
    global matrix
    matrix = False

    Sender.reply("Modo espião ativado")

def mostrar_matrix(Sender, _):
    global matrix
    matrix = True

    Sender.reply("Modo espião desativado")

def verificar_senha(_, data):
    codigo = data.get("senha")
    
    if codigo == senha:
        ui.send_message("liberar", {})

    else:
        ui.send_message("bloquear", {})

def bloquear_servidor(Sender, _):
    global servidor_bloqueado
    
    ui.send_message("bloquear_servidor", {})
    servidor_bloqueado = 0 # Indica ao JS que o servidor deve ser bloqueado

    Sender.reply("Servidor bloqueado")

def desbloquear_servidor(Sender, _):
    global servidor_bloqueado
    
    ui.send_message("desbloquear_servidor", {})
    servidor_bloqueado = 1 # Indica ao JS que o servidor deve ser liberado
    
    Sender.reply("Sevidor desbloqueado")

def envio_ativado(Sender, _):
    global ativar_envio
    ativar_envio = True

    Sender.reply("O envio de images foi ativado")
    
def envio_desativado(Sender, _):
    global ativar_envio
    ativar_envio = False

    Sender.reply("O envio de images foi desativado")

def enviar_permissao(*args):
    global servidorBloqueado
    ui.send_message("permissao", {"servidor": servidor_bloqueado})

def mostrar_comandos(Sender, _):
    comandos = str("/espiao \n /desativar_espiao \n /bloquear_servidor \n /desbloquear_servidor \n /dispositivos \n /ativar_envio \n /desativar_envio \n /comandos \n")
    
    Sender.reply("Comandos: ")
    Sender.reply(comandos)

def disp_conectado(sid):
    global num_dispositivos
    print(f"Dispositivo {sid} foi conectado")
    
    num_dispositivos += 1

    if num_dispositivos <= 1:
        bot.send_message(ID_chat, str(f"{num_dispositivos} dispositivo conectado"))

    else:
        bot.send_message(ID_chat, str(f"{num_dispositivos} dispositivos conectados"))
        

def disp_desconectado(sid):
    global num_dispositivos
    print(f"Dispositivo {sid} foi desconectado")
    
    num_dispositivos -= 1
    bot.send_message(ID_chat, str("Um dispositivo foi desconectado"))

def apr_conectados(Sender, _):
    Sender.reply(f"Numero de dispositivos conectados: {num_dispositivos} | Executar: /bloquear_servidor ?")
    
    
deteccao.on_detect("person", callback_deteccao)

ui.on_message("senha", verificar_senha)
ui.on_message("liberar", enviar_permissao)
ui.on_connect(disp_conectado)
ui.on_disconnect(disp_desconectado)

bot.add_command("espiao", esconder_matrix)
bot.add_command("desativar_espiao", mostrar_matrix)
bot.add_command("bloquear_servidor", bloquear_servidor)
bot.add_command("desbloquear_servidor", desbloquear_servidor)
bot.add_command("comandos", mostrar_comandos)
bot.add_command("dispositivos", apr_conectados)
bot.add_command("ativar_envio", envio_ativado)
bot.add_command("desativar_envio", envio_desativado)

App.run()
