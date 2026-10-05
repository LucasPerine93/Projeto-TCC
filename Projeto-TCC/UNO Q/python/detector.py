from arduino.app_bricks.video_objectdetection import VideoObjectDetection
from arduino.app_peripherals.camera import Camera
import servidor
import math

helmet = False
vest = False

contador_frames = 0

posicao_anterior = None
limite_movimento = 45

camera = Camera(source=0, resolution=(720, 480), fps=10)
deteccao = VideoObjectDetection(camera=camera, debounce_sec=2, confidence=0.5, camera_preview=True)

def verificar_EPIs(specs_frame, frame=None):
    global helmet, vest, posicao_anterior, contador_frames
    
    if frame is None:
        return

    x1, y1, x2, y2 = specs_frame.get('bounding_box_xyxy')
    centro_atual = ((x1 + x2) / 2, (y1 + y2) / 2)

    risco = servidor.risco

    if risco == 1:
        ar_centro = servidor.centro
        ar_widht = servidor.width
        ar_height = servidor.height

        dist1 = math.dist(centro_atual, ar_centro)

        w = float(ar_widht)
        h = float(ar_height)
            
        if dist1 < abs(w) and dist1 < abs(h):
            contador_frames += 1
            if contador_frames >= 2:
                print("[ALERTA]: Operario presente em area de risco")
                contador_frames = 0

    if posicao_anterior is not None:
        distancia = math.dist(centro_atual, posicao_anterior)
        if distancia < limite_movimento:
            return

    if helmet is False:
        print("[LOG]: Capacete não detectado")

    if vest is False:
        print("[LOG]: Colete não detectado")

    if (vest is True) and (helmet is True):
        print("[LOG]: Tudo seguro, EPIs detectados")

    helmet = False
    vest = False

    posicao_anterior = centro_atual


def helmet_detectado(*args):
    global helmet
    helmet = True
    
def vest_detectado(*args):
    global vest
    vest = True

deteccao.on_detect('person', verificar_EPIs)
deteccao.on_detect('helmet', helmet_detectado)
deteccao.on_detect('vest', vest_detectado)
