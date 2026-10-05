import cv2
import asyncio
import websockets

class Servidor:
    def __init__(self, ip: str, porta: int, id_camera: int, resolucao_w: int, resolucao_h: int, resolucao_img: int = 50):

        self.ip = ip
        self.porta = porta
        self.id_camera = id_camera
        self.resolucao_w = resolucao_w
        self.resolucao_h = resolucao_h
        self.resolucao_img = resolucao_img

        self.uri = f"ws://{self.ip}:{self.porta}?raw=true"

        self.cam = cv2.VideoCapture(self.id_camera)
        self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolucao_w)
        self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolucao_h)

    async def transmitir_camera(self):
        while True:
            try:
                print(f"Conectando ao UNO Q em {self.uri}")
                async with websockets.connect(self.uri) as websocket:
                    print("Conexão estabelecida com sucesso!")

                    while self.cam.isOpened():
                        sucesso, frame = self.cam.read()

                        if not sucesso:
                            await asyncio.sleep(0.01)
                            continue

                        sucesso_encode, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, self.resolucao_img])

                        if not sucesso_encode:
                            continue

                        await websocket.send(buffer.tobytes())
                        await asyncio.sleep(0.033)

            except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError) as e:
                print(f"[ERRO]: Conexão perdida ({e}). Tentando reconectar em 2 segundos")
                await asyncio.sleep(2)

if __name__ == "__main__":
    
    cam1 = Servidor(
            ip="192.168.0.113", 
            porta=9393, 
            id_camera=0, 
            resolucao_w=430, 
            resolucao_h=400, 
            resolucao_img=40
        )
    
    asyncio.run(cam1.transmitir_camera())