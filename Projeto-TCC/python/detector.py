"""Detector atual do Lucas com encaminhamento observacional não bloqueante.

As regras de visão (detecção, associação EPI/pessoa, regiões corporais e área
de risco) pertencem a este arquivo. A integração MVP consome apenas a lista
``Operario`` já avaliada; ela não repete a geometria abaixo.

O callback oficial atual ``on_detect_all`` chama ``operario_detectado`` com
apenas ``specs_frame``. A biblioteca/frame não foi validada neste checkout,
logo nenhuma assinatura de dois argumentos ou captura de imagem é assumida.
"""
from dataclasses import dataclass
import math
import os
from pathlib import Path
import sys
import time

from arduino.app_bricks.video_objectdetection import VideoObjectDetection
from arduino.app_peripherals.camera import Camera

import servidor


camera = Camera(source=0, resolution=(720, 480), fps=10)
deteccao = VideoObjectDetection(
    camera=camera,
    debounce_sec=0,
    confidence=0.5,
    camera_preview=False,
)


@dataclass
class Operario:
    box_xyxy: tuple
    tem_colete: bool = False
    tem_capacete: bool = False
    risco_detectado: bool = False
    # Metadados opcionais: preservam o que o modelo já forneceu, sem mudar
    # associação/regiões. O adaptador usa fallback documentado se ausentes.
    conf_pessoa: object = None
    conf_capacete: object = None
    bbox_capacete: object = None
    conf_colete: object = None
    bbox_colete: object = None


def organizar_dado(specs_frame: dict, box_area_risco: tuple, area_risco_ativa: bool):
    """Aplica a lógica geométrica oficial do Lucas a um payload on_detect_all."""
    lista_operarios = []

    pessoas_detectadas = specs_frame.get("person", [])
    if pessoas_detectadas == []:
        # Compatibilidade deliberada com o comportamento publicado do Lucas.
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
                centro_cabeca_operario, centro_capacete = calcular_centro_com_regiao(
                    operario.box_xyxy, box_capacete, 0.10
                )
                dist = calcular_distacia(centro_capacete, centro_cabeca_operario)
                if dist < menor_distancia:
                    menor_distancia = dist
                    melhor_operario = operario

        if melhor_operario is not None:
            melhor_operario.tem_capacete = True
            melhor_operario.conf_capacete = dados_capacete.get("confidence")
            melhor_operario.bbox_capacete = box_capacete

    coletes_detectados = specs_frame.get("vest", [])
    for dados_colete in coletes_detectados:
        melhor_operario = None
        menor_distancia = float("inf")
        box_colete = dados_colete["bounding_box_xyxy"]

        for operario in lista_operarios:
            # Região de 36% a 80% do corpo fica o colete.
            if verificar_epi(box_colete, operario.box_xyxy, (0.36, 0.80)):
                centro_tronco_operario, centro_colete = calcular_centro_com_regiao(
                    operario.box_xyxy, box_colete, 0.55
                )
                dist = calcular_distacia(centro_colete, centro_tronco_operario)
                if dist < menor_distancia:
                    menor_distancia = dist
                    melhor_operario = operario

        if melhor_operario is not None:
            melhor_operario.tem_colete = True
            melhor_operario.conf_colete = dados_colete.get("confidence")
            melhor_operario.bbox_colete = box_colete

    if area_risco_ativa is True:
        for operario in lista_operarios:
            if verificar_area_risco(box_area_risco, operario.box_xyxy):
                operario.risco_detectado = True

    analisar_seguranca(lista_operarios)
    return lista_operarios


ultimo_alerta = 0
TEMPO_ESPERA = 5


def analisar_seguranca(lista_de_operarios):
    """Logs originais do Lucas: terminal e WebUI, sem depender do MVP."""
    global ultimo_alerta
    tempo_atual = time.time()

    if (tempo_atual - ultimo_alerta) >= TEMPO_ESPERA:
        for operario in lista_de_operarios:
            if (
                operario.tem_colete is True
                and operario.tem_capacete is True
                and operario.risco_detectado is False
            ):
                mensagem = "[OK]: Operario com todos os EPIs e seguro!"
                print(mensagem)
                servidor.enviar_log(mensagem)

            if operario.tem_colete is False:
                mensagem = f"[ALERTA]: Operario na posição {operario.box_xyxy} identificado sem colete!"
                print(mensagem)
                servidor.enviar_log(mensagem)

            if operario.tem_capacete is False:
                mensagem = f"[ALERTA]: Operario na posição {operario.box_xyxy} identificado sem capacete!"
                print(mensagem)
                servidor.enviar_log(mensagem)

            if operario.risco_detectado is True:
                mensagem = f"[ALERTA]: Operario na posição {operario.box_xyxy} está em área de risco!"
                print(mensagem)
                servidor.enviar_log(mensagem)
        ultimo_alerta = tempo_atual


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


# ---------------------------------------------------------------------------
# Integração observacional: carregamento portável e degradação explícita.
# Não importa a State Machine de montagem e não refaz geometria do detector.
# ---------------------------------------------------------------------------
def _raiz_mvp():
    raiz_env = os.environ.get("TCC_MVP_ROOT")
    if raiz_env:
        candidato = Path(raiz_env)
        if (candidato / "vision_integration" / "integracao_lucas.py").is_file():
            return candidato

    atual = Path(__file__).resolve().parent
    for _ in range(6):
        candidato = atual / "procedimento-mvp"
        if (candidato / "vision_integration" / "integracao_lucas.py").is_file():
            return candidato
        if (atual / "vision_integration" / "integracao_lucas.py").is_file():
            return atual
        atual = atual.parent
    return None


_processar_operarios = None
_erro_integracao = None


def _inicializar_integracao():
    """Configura o hook uma vez; erro não interrompe a visão nem fica oculto."""
    global _processar_operarios, _erro_integracao
    raiz = _raiz_mvp()
    if raiz is None:
        _erro_integracao = "procedimento-mvp/vision_integration não encontrado"
        print(f"[VISION] integração observacional indisponível: {_erro_integracao}")
        return

    for pasta in (raiz, raiz / "event_arch"):
        texto = str(pasta)
        if texto not in sys.path:
            sys.path.insert(0, texto)
    try:
        from vision_integration import integracao_lucas
        from vision_integration.detector_bridge import DetectorIngestBridge
        from vision_integration.occurrence import OccurrenceTracker
        from event_debounce import EventDebounce
        from event_log import EventLog

        integracao_lucas.configurar(
            log=EventLog(raiz / "data" / "procedure_events.jsonl"),
            debounce=EventDebounce(),
            ponte=DetectorIngestBridge(),
            occurrence=OccurrenceTracker(),
        )
        _processar_operarios = integracao_lucas.processar_operarios
        print("[VISION] integração observacional configurada -> Operario -> adapter")
    except Exception as exc:  # detector continua funcionando sem o MVP
        _erro_integracao = repr(exc)
        print(f"[VISION] integração observacional indisponível: {_erro_integracao}")


def operario_detectado(specs_frame):
    """Callback oficial do Lucas: um argumento, sem supor frame disponível."""
    risco = servidor.risco
    box_risco = servidor.box_risco
    operarios = organizar_dado(specs_frame, box_risco, bool(risco))

    if _processar_operarios is None:
        return operarios
    try:
        # O adapter usa o veredicto risco_detectado/tem_* já definido acima.
        # specs_frame é preservado como payload bruto da ingestão; não há frame
        # aqui porque a API atual do callback não o documenta/disponibiliza.
        resumo = _processar_operarios(
            operarios,
            specs_frame=specs_frame,
            box_risco=box_risco,
            area_ativa=bool(risco),
        )
        if not resumo.get("ok", False):
            print("[VISION] integração observacional concluiu com erro registrado")
    except Exception as exc:  # defesa extra: callback da câmera nunca cai
        print(f"[VISION] integração observacional falhou no callback: {exc!r}")
    return operarios


_inicializar_integracao()
deteccao.on_detect_all(operario_detectado)