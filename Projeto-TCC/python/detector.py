from arduino.app_bricks.video_objectdetection import VideoObjectDetection
from arduino.app_peripherals.camera import Camera
from dataclasses import dataclass
import servidor
import math

camera = Camera(source=0, resolution=(720, 480), fps=10)
deteccao = VideoObjectDetection(camera=camera, debounce_sec=0, confidence=0.5, camera_preview=True)

@dataclass
class Operario:
    box_xyxy: tuple
    tem_colete: bool = False
    tem_capacete:bool = False
    risco_detectado: bool = False


def organizar_dado(specs_frame: dict, box_area_risco: tuple, area_risco_ativa: bool):
    lista_operarios = []

    pessoas_detectadas = specs_frame.get("person", [])
    if pessoas_detectadas == []:
        return
    
    for dados_pessoa in pessoas_detectadas:
        novo_operario = Operario(box_xyxy=dados_pessoa["bounding_box_xyxy"])
        lista_operarios.append(novo_operario)


    capacetes_detectados = specs_frame.get("helmet", [])
    for dados_capacete in capacetes_detectados:
        box_capacete = dados_capacete['bounding_box_xyxy']

        for operario in lista_operarios:
            if verificar_area(box_capacete, operario.box_xyxy) == True:
                operario.tem_capacete = True


    coletes_detectados = specs_frame.get("vest", [])
    for dados_colete in coletes_detectados:
        box_colete = dados_colete['bounding_box_xyxy']

        for operario in lista_operarios:
            if verificar_area(box_colete, operario.box_xyxy) == True:
                operario.tem_colete = True

    if area_risco_ativa == True:
        for operario in lista_operarios:
            if verificar_area(box_area_risco, operario.box_xyxy) == True:
                operario.risco_detectado = True

    analisar_seguranca(lista_operarios)

    return lista_operarios

def analisar_seguranca(lista_de_operarios):
    for operario in lista_de_operarios:
        if operario.tem_colete == True and operario.tem_capacete == True and operario.risco_detectado == False:
            print("[OK]: Operario com todos os EPIs e seguro!")

        if operario.tem_colete == False:
            print(f"[ALERTA]: Operario na posição {operario.box_xyxy} identificado sem colete!")

        if operario.tem_capacete == False:
            print(f"[ALERTA]: Operario na posição {operario.box_xyxy} identificado sem capacete!")

        if operario.risco_detectado == True:
            print(f"[ALERTA]: Operario na posição {operario.box_xyxy} está em área de risco!")

def verificar_area(box_epi, box_pessoa) -> bool:
    px1, py1, px2, py2 = box_pessoa
    ex1, ey1, ex2, ey2 = box_epi

    centro_x = ((ex1 + ex2) / 2)
    centro_y = ((ey1 + ey2) / 2)

    if centro_x > px1 and centro_x < px2 and centro_y > py1 and centro_y < py2:
        return True

    else:
        return False

def operario_detectado(specs_frame):
    risco = servidor.risco
    box_risco = servidor.box_risco

    if risco == False: # 0 é falso então e função recebe False para o risco
        organizar_dado(specs_frame, box_risco, False)
        
    else:
        organizar_dado(specs_frame, box_risco, True)

deteccao.on_detect_all(operario_detectado)