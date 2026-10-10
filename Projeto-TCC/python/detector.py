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

        for operario in lista_operarios: # Região do topo a 35% do corpo fica o capacete
            if verificar_epi(box_capacete, operario.box_xyxy, (-0.15, 0.35)) == True:
                operario.tem_capacete = True


    coletes_detectados = specs_frame.get("vest", [])
    for dados_colete in coletes_detectados:
        box_colete = dados_colete['bounding_box_xyxy']

        for operario in lista_operarios: # Região de 36% do corpo até 80% fica o colete
            if verificar_epi(box_colete, operario.box_xyxy, (0.36, 0.80)) == True:
                operario.tem_colete = True

    if area_risco_ativa == True:
        for operario in lista_operarios:
            if verificar_area_risco(box_area_risco, operario.box_xyxy) == True:
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

def verificar_area_risco(box_risco, box_pessoa) -> bool:
    if not box_risco or not box_pessoa:
        return False
    
    # 'p' para Pessoa, 'r' para Risco
    px1, py1, px2, py2 = box_pessoa
    rx1, ry1, rx2, ry2 = box_risco

    pe_x = ((px1 + px2) / 2) # Localiza o meio (X) da caixa do operario
    pe_y = py2 # Localiza o pé do operario 

    if rx1 <= pe_x <= rx2 and ry1 <= pe_y <= ry2:
        return True

    else:
        return False

def verificar_epi(box_epi, box_operario, local_corpo) -> bool:
    # 'o' para Operário, 'e' para EPI
    ox1, oy1, ox2, oy2 = box_operario
    ex1, ey1, ex2, ey2 = box_epi

    altura = abs(oy1 - oy2)

    centro_x_epi = ((ex1 + ex2) / 2)
    centro_y_epi = ((ey1 + ey2) / 2)

    zona_topo = oy1 + local_corpo[0] * altura
    zona_base = oy1 + local_corpo[1] * altura

    # O centro do EPI está dentro da largura do operário e dentro da faixa vertical da região?
    # Olha a região do EPI no corpo do operário

    if ox1 <= centro_x_epi <= ox2 and zona_topo <= centro_y_epi <= zona_base:
        return True

    else:
        return False

def operario_detectado(specs_frame):
    risco = servidor.risco
    box_risco = servidor.box_risco

    if risco == False:
        organizar_dado(specs_frame, box_risco, False)
        
    else:
        organizar_dado(specs_frame, box_risco, True)

deteccao.on_detect_all(operario_detectado)