import cv2
import asyncio
import websockets
import numpy as np
import threading


class Camera:
    def __init__(self, id_camera: int, resolucao_w: int, resolucao_h: int):
        self.id_camera = id_camera
        self.resolucao_w = resolucao_w
        self.resolucao_h = resolucao_h

        self.cam = cv2.VideoCapture(self.id_camera)
        self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolucao_h)
        self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolucao_w)
        self.cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

    def pegar_video(self) -> np.ndarray | None:
        sucesso, buffer = self.cam.read()

        if not sucesso or buffer is None:
            return None
        
        return cv2.resize(buffer, (self.resolucao_w, self.resolucao_h), interpolation=cv2.INTER_NEAREST)

    def liberar(self):
        self.cam.release()

class Frame:
    def __init__(self, qualidade_img, cam1, cam2):
        self.qualidade_img = qualidade_img

        self.cam1 = cam1
        self.cam2 = cam2

    def juntar_frame(self) -> np.ndarray | None:
        
        frame1 = self.cam1.pegar_video()
        frame2 = self.cam2.pegar_video()

        if frame1 is None or frame2 is None:
            return
        
        if frame1.shape[0] == frame2.shape[0]:
            imagem_combinada = cv2.hconcat([frame1, frame2])
            sucesso, frame = cv2.imencode('.jpg', imagem_combinada, [cv2.IMWRITE_JPEG_QUALITY, self.qualidade_img])

            if sucesso == True:
                return frame

        else:
            print("Erro: As imagens têm alturas diferentes! É necessário redimensionar antes.")
            return None

class Servidor:
    def __init__(self, ip, porta, juntar):
        self.ip = ip
        self.porta = porta
        self.juntar = juntar

        self.uri = f"ws://{self.ip}:{self.porta}?raw=true"

    async def enviar_frames(self):
        while True:
            try:
                print(f"Conectando ao UNO Q em {self.uri}")
                async with websockets.connect(self.uri) as ws:
                    print("Conectado a placa UNO Q")
                    while True:
                        img = self.juntar.juntar_frame()

                        if img is not None:
                            await ws.send(img.tobytes())

                        await asyncio.sleep(0.001)

            except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError, AttributeError) as e:
                print(f"[ERRO]: Conexão perdida ({e}). Tentando reconectar em 2 segundos")
                await asyncio.sleep(2)

if __name__ == "__main__":

    cam1 = Camera(
        id_camera=1,
        resolucao_w=600,
        resolucao_h=420
    )
              
    cam2 = Camera(
        id_camera=0,
        resolucao_w=600,
        resolucao_h=420
    )
          
    juntar = Frame(qualidade_img=20, cam1=cam1, cam2=cam2)
    transmitir = Servidor(porta=9393, ip="192.168.0.113", juntar=juntar)

    try:
        asyncio.run(transmitir.enviar_frames())

    except KeyboardInterrupt:
        cam1.liberar()
        cam2.liberar()
        print("Programa finalizado")