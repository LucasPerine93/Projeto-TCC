from arduino.app_bricks.video_objectdetection import VideoObjectDetection
from arduino.app_peripherals.camera import Camera

from dataclasses import dataclass
import math
import time

import servidor
import banco

camera = Camera(source=0, resolution=(720, 480), fps=10)
deteccao = VideoObjectDetection(
    camera=camera,
    debounce_sec=0,
    confidence=0.5,
    camera_preview=True,
)


@dataclass
class Operario:
    box_xyxy: tuple
    id: int | None = None
    tem_colete: bool = False
    tem_capacete: bool = False
    risco_detectado: bool = False

    # Começa None mas depois vai receber um float por isso -> float | None
    conf_pessoa: float | None = None
    conf_capacete: float | None = None
    conf_colete: float | None = None

def organizar_dado(specs_frame: dict, box_area_risco: tuple, area_risco_ativa: bool, frame):
    lista_operarios = []

    pessoas_detectadas = specs_frame.get("person", [])
    if pessoas_detectadas == []:
        return

    for dados_pessoa in pessoas_detectadas:
        novo_operario = Operario(
            box_xyxy=dados_pessoa["bounding_box_xyxy"],
            conf_pessoa=dados_pessoa.get("confidence"),
        )
        lista_operarios.append(novo_operario)

    capacetes_detectados = specs_frame.get("helmet", [])
    for dados_capacete in capacetes_detectados:
        melhor_operario = None
        menor_distancia = float("inf")
        box_capacete = dados_capacete["bounding_box_xyxy"]

        for operario in lista_operarios:
            # Região do topo a 35% do corpo fica o capacete.
            if verificar_epi(box_capacete, operario.box_xyxy, (-0.15, 0.35)):
                centro_cabeca_operario, centro_capacete = calcular_centro_com_regiao(operario.box_xyxy, box_capacete, 0.10) # Posiciona o centro na testa do operario
                dist = calcular_distacia(centro_capacete, centro_cabeca_operario)
                if dist < menor_distancia:
                    menor_distancia = dist
                    melhor_operario = operario

        if melhor_operario is not None:
            melhor_operario.tem_capacete = True
            melhor_operario.conf_capacete = dados_capacete.get("confidence")

    coletes_detectados = specs_frame.get("vest", [])
    for dados_colete in coletes_detectados:
        melhor_operario = None
        menor_distancia = float("inf")
        box_colete = dados_colete["bounding_box_xyxy"]

        for operario in lista_operarios:
            # Região de 36% a 80% do corpo fica o colete.
            if verificar_epi(box_colete, operario.box_xyxy, (0.36, 0.80)):
                centro_tronco_operario, centro_colete = calcular_centro_com_regiao(operario.box_xyxy, box_colete, 0.55)
                dist = calcular_distacia(centro_colete, centro_tronco_operario)
                if dist < menor_distancia:
                    menor_distancia = dist
                    melhor_operario = operario

        if melhor_operario is not None:
            melhor_operario.tem_colete = True
            melhor_operario.conf_colete = dados_colete.get("confidence")

    if area_risco_ativa == True:
        for operario in lista_operarios:
            if verificar_area_risco(box_area_risco, operario.box_xyxy):
                operario.risco_detectado = True

    analisar_seguranca(lista_operarios)
    rastrear_operarios(lista_operarios, frame)

salvar_imagem = False
def analisar_seguranca(lista_de_operarios):
    global salvar_imagem
    for operario in lista_de_operarios:
        if (operario.tem_colete is True and operario.tem_capacete is True and operario.risco_detectado is False):
            mensagem = "[OK]: Operario com todos os EPIs e seguro!"
            print(mensagem)
            servidor.enviar_log(mensagem)
            salvar_imagem = False

        if operario.tem_colete is False:
            mensagem = f"[ALERTA]: Operario na posição {operario.box_xyxy} identificado sem colete!"
            print(mensagem)
            servidor.enviar_log(mensagem)
            salvar_imagem = True

        if operario.tem_capacete is False:
            mensagem = f"[ALERTA]: Operario na posição {operario.box_xyxy} identificado sem capacete!"
            print(mensagem)
            servidor.enviar_log(mensagem)
            salvar_imagem = True

        if operario.risco_detectado is True:
            mensagem = f"[ALERTA]: Operario na posição {operario.box_xyxy} está em área de risco!"
            print(mensagem)
            servidor.enviar_log(mensagem)
            salvar_imagem = True


def filtrar_salvamento(lista_de_operarios, frame):
    global salvar_imagem

    if salvar_imagem == True:
        for operario in lista_de_operarios:
            if operario.tem_colete == True and operario.tem_capacete == True:
                banco.salvar_ocorrencias("Seguro, todos os EPIs detectados", operario.box_xyxy, operario.conf_pessoa, operario.conf_capacete, operario.conf_colete, frame)

            if operario.tem_colete == False and operario.tem_capacete == True:
                banco.salvar_ocorrencias("Sem colete", operario.box_xyxy, operario.conf_pessoa, operario.conf_capacete, operario.conf_colete, frame)

            if operario.tem_colete == True and operario.tem_capacete == False:
                banco.salvar_ocorrencias("Sem capacete", operario.box_xyxy, operario.conf_pessoa, operario.conf_capacete, operario.conf_colete, frame)

            if operario.tem_colete == False and operario.tem_capacete == False:
                banco.salvar_ocorrencias("Sem capacete e colete", operario.box_xyxy, operario.conf_pessoa, operario.conf_capacete, operario.conf_colete, frame)

        salvar_imagem = False

dados_operarios = {}
DISTANCIA_MAXIMA = 90
proximo_id = 0
def rastrear_operarios(lista_operarios, frame):
    global dados_operarios, proximo_id

    ids_ja_usados_neste_frame = set()
    tempo_atual = time.time()

    ids_para_remover = []
    if dados_operarios is not None:
        for id_cadastrado, dado_operario in dados_operarios.items():
            if abs(dado_operario["visto_por_ultimo"] - tempo_atual) > 20:
                ids_para_remover.append(id_cadastrado)
    
        if ids_para_remover is not None:
            for id_remover in ids_para_remover:
                del dados_operarios[id_remover]

    for operario in lista_operarios:
        if operario.id in ids_ja_usados_neste_frame:
            continue 

        x1, y1, x2, y2 = operario.box_xyxy
        centro_op_detectado = ((x1 + x2) / 2, (y1 + y2) / 2)
        id_encontrado = None

        for id_cadastrado, dado_operario in dados_operarios.items():
            if id_cadastrado in ids_ja_usados_neste_frame:
                continue

            distancia = math.dist(dado_operario["centro"], centro_op_detectado)
            if distancia < DISTANCIA_MAXIMA:
                id_encontrado = id_cadastrado
                break

        if id_encontrado is not None:
            operario.id = id_encontrado
            dados_operarios[id_encontrado]["centro"] = centro_op_detectado
            dados_operarios[id_encontrado]["visto_por_ultimo"] = tempo_atual

        else:
            operario.id = proximo_id
            dados_operarios[proximo_id] = {
                "centro": centro_op_detectado,
                "visto_por_ultimo": tempo_atual,
                "ultimo_salvamento": 0
            }
            proximo_id += 1

        ids_ja_usados_neste_frame.add(operario.id)

        if dados_operarios[operario.id]["ultimo_salvamento"] == 0:
            filtrar_salvamento(lista_operarios, frame)
            dados_operarios[operario.id]["ultimo_salvamento"] = tempo_atual
            print(dados_operarios)

        elif abs(dados_operarios[operario.id]["ultimo_salvamento"] - tempo_atual) > 20:
            filtrar_salvamento(lista_operarios, frame)
            dados_operarios[operario.id]["ultimo_salvamento"] = tempo_atual
            print(dados_operarios)

        else:
            continue

def verificar_area_risco(box_risco, box_pessoa) -> bool:
    if not box_risco or not box_pessoa:
        return False

    px1, py1, px2, py2 = box_pessoa
    rx1, ry1, rx2, ry2 = box_risco
    centro_x = (px1 + px2) / 2
    centro_y = (py1 + py2) / 2
    return rx1 <= centro_x <= rx2 and ry1 <= centro_y <= ry2


def verificar_epi(box_epi, box_operario, local_corpo) -> bool:
    ox1, oy1, ox2, oy2 = box_operario
    ex1, ey1, ex2, ey2 = box_epi
    altura = abs(oy1 - oy2)
    centro_x_epi = (ex1 + ex2) / 2
    centro_y_epi = (ey1 + ey2) / 2
    zona_topo = oy1 + local_corpo[0] * altura
    zona_base = oy1 + local_corpo[1] * altura
    return ox1 <= centro_x_epi <= ox2 and zona_topo <= centro_y_epi <= zona_base


def calcular_distacia(posicao1, posicao2) -> float:
    return math.dist(posicao1, posicao2)


def calcular_centro_com_regiao(box_operario, box_epi, regiao) -> tuple:
    ox1, oy1, ox2, oy2 = box_operario
    ex1, ey1, ex2, ey2 = box_epi
    altura = abs(oy2 - oy1)
    y_epi = oy1 + altura * regiao
    centro_operario = ((ox1 + ox2) / 2, y_epi)
    centro_epi = ((ex1 + ex2) / 2, (ey1 + ey2) / 2)
    return centro_operario, centro_epi


def operario_detectado(specs_frame, frame=None):
    if frame == None:
        return

    risco = servidor.risco
    box_risco = servidor.box_risco
    organizar_dado(specs_frame, box_risco, risco, frame)


deteccao.on_detect_all(operario_detectado)