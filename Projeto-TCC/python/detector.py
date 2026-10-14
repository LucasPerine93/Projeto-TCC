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
    tem_colete: bool = False
    tem_capacete: bool = False
    risco_detectado: bool = False

    # Começa None mas depois vai receber um float por isso -> float | None
    conf_pessoa: float | None = None
    conf_capacete: float | None = None
    conf_colete: float | None = None

    # Caixas reais (bounding boxes em pixels do frame) dos EPIs associados.
    # Começam None e são preenchidas em organizar_dado quando há associação.
    box_capacete: tuple | None = None
    box_colete: tuple | None = None

    # Trilha efemera atribuida por rastreamento geometrico entre frames.
    # Nao identifica a pessoa de forma permanente.
    track_id: int | None = None


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
            if verificar_epi(box_capacete, operario.box_xyxy, (-0.15, 0.35)): # (0.10) Posiciona o centro na testa do operario
                centro_cabeca_operario, centro_capacete = calcular_centro_com_regiao(operario.box_xyxy, box_capacete, 0.10) 
                dist = calcular_distacia(centro_capacete, centro_cabeca_operario)
                if dist < menor_distancia:
                    menor_distancia = dist
                    melhor_operario = operario

        if melhor_operario is not None:
            melhor_operario.tem_capacete = True
            melhor_operario.conf_capacete = dados_capacete.get("confidence")
            melhor_operario.box_capacete = box_capacete

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
            melhor_operario.box_colete = box_colete

    if area_risco_ativa == True:
        for operario in lista_operarios:
            if verificar_area_risco(box_area_risco, operario.box_xyxy):
                operario.risco_detectado = True

    analisar_seguranca(lista_operarios)
    filtrar_salvamento(lista_operarios, frame)
    return lista_operarios


ultimo_alerta = 0
TEMPO_ESPERA = 5

def analisar_seguranca(lista_de_operarios):

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

# ---------------------------------------------------------------------------
# Rastreamento temporario por trilha (sem identificacao civil permanente)
# ---------------------------------------------------------------------------
# Cada pessoa recebe um ``track_id`` efemero, associado entre frames consecutivos
# por IoU das caixas e por distancia entre centros proporcional ao tamanho da
# propria caixa. Nao ha reconhecimento facial nem identidade estavel no tempo:
# e apenas continuidade geometrica, suficiente para nao repetir a mesma
# ocorrencia da mesma trajetoria.

LIMIAR_IOU = 0.15          # IoU minimo para considerar a mesma trajetoria
LIMIAR_DISTANCIA = 0.6     # fracao da menor diagonal entre as duas caixas
MARGEM_AMBIGUIDADE = 0.05  # diferenca minima de placar para descartar empate
TEMPO_VIDA_TRILHA = 5.0    # segundos sem ver a pessoa para esquecer a trilha
TEMPO_ESPERA_SALVAR = 20   # cooldown POR trilha e POR tipo de infracao

_proximo_track_id = 1
_trilhas_ativas = {}       # track_id -> {"box": tuple, "visto_em": float}
_ultima_ocorrencia = {}    # (track_id, tipo_infracao) -> timestamp


def calcular_iou(box_a, box_b):
    """Intersection over Union entre duas caixas (x1, y1, x2, y2)."""
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    area_inter = max(0.0, inter_x2 - inter_x1) * max(0.0, inter_y2 - inter_y1)
    if area_inter <= 0:
        return 0.0

    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    area_uniao = area_a + area_b - area_inter
    if area_uniao <= 0:
        return 0.0
    return area_inter / area_uniao


def calcular_centro(box):
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def calcular_diagonal(box):
    x1, y1, x2, y2 = box
    return math.dist((x1, y1), (x2, y2))


def pontuar_associacao(box_atual, box_anterior):
    """Combina IoU e distancia proporcional num unico placar de similaridade."""
    iou = calcular_iou(box_atual, box_anterior)
    distancia = math.dist(calcular_centro(box_atual), calcular_centro(box_anterior))

    # Menor diagonal como referencia de escala: evita que uma caixa grande
    # "engula" uma pessoa pequena (e vice-versa) em escalas diferentes.
    escala = min(calcular_diagonal(box_atual), calcular_diagonal(box_anterior))
    if escala <= 0:
        return None

    distancia_relativa = distancia / escala
    return {
        "iou": iou,
        "distancia_relativa": distancia_relativa,
        "placar": iou - 0.5 * distancia_relativa,
    }


def associar_trilhas(lista_de_operarios, agora):
    """Atribui um ``track_id`` efemero a cada operario do frame atual."""
    global _proximo_track_id, _trilhas_ativas

    for trilha_id in list(_trilhas_ativas.keys()):
        if (agora - _trilhas_ativas[trilha_id]["visto_em"]) > TEMPO_VIDA_TRILHA:
            del _trilhas_ativas[trilha_id]

    candidatas = sorted(_trilhas_ativas.items())
    usadas = set()

    for operario in lista_de_operarios:
        melhor = None
        segundo = None

        for trilha_id, dados in candidatas:
            if trilha_id in usadas:
                continue

            pontos = pontuar_associacao(operario.box_xyxy, dados["box"])
            if pontos is None:
                continue

            compativel = (
                pontos["iou"] >= LIMIAR_IOU
                or pontos["distancia_relativa"] <= LIMIAR_DISTANCIA
            )
            if not compativel:
                continue

            if melhor is None or pontos["placar"] > melhor[1]["placar"]:
                segundo = melhor
                melhor = (trilha_id, pontos)
            elif segundo is None or pontos["placar"] > segundo[1]["placar"]:
                segundo = (trilha_id, pontos)

        # Cruzamento ambiguo (duas trilhas praticamente empatadas): nao
        # presumimos identidade e abrimos uma trilha nova.
        if (
            melhor is not None
            and segundo is not None
            and abs(melhor[1]["placar"] - segundo[1]["placar"]) < MARGEM_AMBIGUIDADE
        ):
            melhor = None

        if melhor is not None:
            trilha_id = melhor[0]
        else:
            trilha_id = _proximo_track_id
            _proximo_track_id += 1

        usadas.add(trilha_id)
        operario.track_id = trilha_id
        _trilhas_ativas[trilha_id] = {"box": operario.box_xyxy, "visto_em": agora}

    return lista_de_operarios

def classificar_infracao(operario):
    """Tipo de infracao do operario, ou None quando estiver conforme.

    Invasao de area de risco entra nas regras de salvamento: quem usa todos os
    EPIs mas permanece na area de risco continua gerando ocorrencia.
    """
    if not operario.tem_colete and not operario.tem_capacete:
        return "Sem capacete e colete"
    if not operario.tem_colete:
        return "Sem colete"
    if not operario.tem_capacete:
        return "Sem capacete"
    if operario.risco_detectado:
        return "Invasao de area de risco"
    return None


def montar_cena(lista_de_operarios):
    """Lista serializavel de TODOS os trabalhadores vistos na cena."""
    cena = []
    for outro in lista_de_operarios:
        if getattr(outro, "track_id", None) is None:
            continue
        cena.append({
            "track_id": outro.track_id,
            "tipo_infracao": classificar_infracao(outro),
            "risco_detectado": bool(outro.risco_detectado),
            "conf_pessoa": outro.conf_pessoa,
            "conf_capacete": outro.conf_capacete,
            "conf_colete": outro.conf_colete,
            "pessoa": [int(v) for v in outro.box_xyxy],
            "capacete": [int(v) for v in outro.box_capacete] if outro.box_capacete else None,
            "colete": [int(v) for v in outro.box_colete] if outro.box_colete else None,
        })
    return cena


def filtrar_salvamento(lista_de_operarios, frame):
    """Avalia CADA pessoa do frame individualmente e persiste as infracoes.

    Diferencas em relacao ao cooldown global anterior:

    * uma pessoa em conformidade nunca zera o registro de outra irregular;
    * duas pessoas diferentes nunca se bloqueiam entre si;
    * a repeticao e controlada por (track_id, tipo_infracao);
    * um unico arquivo .jpg e gravado por cena, mesmo com varios registros.
    """
    agora = time.time()
    if not lista_de_operarios:
        return

    associar_trilhas(lista_de_operarios, agora)

    aprovados = []
    for operario in lista_de_operarios:
        tipo = classificar_infracao(operario)
        if tipo is None:
            continue

        chave = (operario.track_id, tipo)
        anterior = _ultima_ocorrencia.get(chave)
        if anterior is not None and (agora - anterior) < TEMPO_ESPERA_SALVAR:
            continue  # mesma trajetoria, mesmo problema, ainda no cooldown

        aprovados.append((operario, tipo))

    if not aprovados:
        return

    registros = [
        {
            "tipo_infracao": tipo,
            "posicao_operario": operario.box_xyxy,
            "conf_pessoa": operario.conf_pessoa,
            "conf_capacete": operario.conf_capacete,
            "conf_colete": operario.conf_colete,
            "box_capacete": operario.box_capacete,
            "box_colete": operario.box_colete,
        }
        for operario, tipo in aprovados
    ]

    salvos = banco.salvar_cena(frame, registros, montar_cena(lista_de_operarios))

    # So marca o cooldown do que realmente chegou ao banco.
    if salvos:
        for operario, tipo in aprovados:
            _ultima_ocorrencia[(operario.track_id, tipo)] = agora

    # Limpa chaves antigas para o dicionario nao crescer sem limite.
    for chave in list(_ultima_ocorrencia.keys()):
        if (agora - _ultima_ocorrencia[chave]) > (TEMPO_ESPERA_SALVAR * 3):
            del _ultima_ocorrencia[chave]


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