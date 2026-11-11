from arduino.app_bricks.video_objectdetection import VideoObjectDetection
from arduino.app_peripherals.camera import Camera

from dataclasses import dataclass
import math
import time
import traceback

import config
import servidor
import banco
import amostragem

camera = Camera(source=config.CAMERA_SOURCE, resolution=config.CAMERA_RESOLUTION, fps=config.CAMERA_FPS)
try:
    deteccao = VideoObjectDetection(
        camera=camera,
        debounce_sec=config.DETECCAO_DEBOUNCE_SEC,
        confidence=config.DETECCAO_CONFIANCA,
        camera_preview=True,
    )
except TypeError:
    # Lib antiga (pin 6735581): sem camera_preview e sem frame no callback.
    deteccao = VideoObjectDetection(
        camera=camera,
        debounce_sec=config.DETECCAO_DEBOUNCE_SEC,
        confidence=config.DETECCAO_CONFIANCA,
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

    # Posição no mundo (metros, origem no centro do galpão), projetada a partir
    # do ponto dos pés (centro horizontal da caixa, base vertical) pela
    # homografia H da calibração ativa. None quando não há calibração válida.
    pos_x_m: float | None = None
    pos_z_m: float | None = None
    celula_idx: int | None = None


# Faixa vertical do corpo (fração da altura da caixa da pessoa, medida a
# partir do topo) onde cada EPI deve ter o seu centro.
# Valores centrais em config.py (fonte unica); aliases abaixo por compatibilidade.
ZONA_CAPACETE = config.ZONA_CAPACETE
ZONA_COLETE = config.ZONA_COLETE


# ---------------------------------------------------------------------------
# Conversões seguras (NumPy -> tipos nativos)
# ---------------------------------------------------------------------------
def _to_float(val, default=0.0):
    """Converte ``val`` em ``float`` nativo ou devolve ``default``.

    Trata ``None``, ``bool``, ``int``, ``float``, strings (com vírgula decimal),
    escalares NumPy (``np.floating``/``np.integer``) e ``np.ndarray`` com um
    único elemento. Arrays maiores, listas, NaN e infinito retornam ``default``.
    """
    if val is None:
        return default

    # NumPy: escalar (np.float32, np.int64...) ou array de 1 elemento.
    # Não importa o numpy aqui: ``size``/``item`` bastam (duck typing).
    if hasattr(val, "item") and hasattr(val, "dtype"):
        try:
            if getattr(val, "size", 1) != 1:
                return default
            val = val.item()
        except Exception:
            return default

    if isinstance(val, bool):
        return float(val)

    if isinstance(val, str):
        texto = val.strip().replace(",", ".")
        if not texto:
            return default
        try:
            val = float(texto)
        except ValueError:
            return default

    try:
        resultado = float(val)
    except (TypeError, ValueError, OverflowError):
        return default

    if math.isnan(resultado) or math.isinf(resultado):
        return default
    return resultado


def _to_xyxy(dado: dict, chaves: list[str], default: float) -> list[float]:
    """Extrai a caixa ``(x1, y1, x2, y2)`` de qualquer chave conhecida,
    normalizando NumPy -> nativo e forçando o tipo numérico."""
    valor = None
    for chave in chaves:
        if chave in dado and dado[chave] is not None:
            valor = dado[chave]
            break

    if valor is None:
        return [default, default, default, default]

    try:
        if hasattr(valor, "tolist"):
            valor = valor.tolist()
    except Exception:
        pass

    if isinstance(valor, (list, tuple)):
        if len(valor) < 4:
            return [default, default, default, default]
        return [_to_float(valor[i], default) for i in range(4)]

    return [default, default, default, default]


def _get_conf(dado: dict) -> float:
    """Encontra a chave de confiança (``confidence``) com fallback para
    ``score``/``conf``. Retorna ``0.0`` quando ausente, ``None`` ou inválida:
    nunca inventa uma confiança."""
    if not isinstance(dado, dict):
        return 0.0
    for chave in ("confidence", "score", "conf"):
        if chave in dado and dado[chave] is not None:
            return _to_float(dado[chave], 0.0)
    return 0.0


def _get_pessoa(specs_frame: dict) -> list[dict]:
    """Normaliza a chave da lista de pessoas (``person``/``people``)
    e os campos das mesmas, de forma a não quebrar a lib YOLOX de produção."""
    pessoas = specs_frame.get("person", specs_frame.get("people", []))
    if pessoas is None:
        pessoas = []
    return [p for p in pessoas if isinstance(p, dict)]


# ---------------------------------------------------------------------------
# Projeção do ponto dos pés para a planta do gêmeo 3D (Etapa 3)
# ---------------------------------------------------------------------------
PLANTA_LARGURA_M = 40.0
PLANTA_ALTURA_M = 30.0
MAPA_COLUNAS = 80
MAPA_LINHAS = 60
CELULA_M = 0.5
# Resolução do frame em que o detector trabalha (fonte dos dados de entrada)
FRAME_DETECTOR_W, FRAME_DETECTOR_H = 720, 480


def projetar_pe_para_planta(box_xyxy, calibracao):
    """Projeta o ponto dos pés de uma caixa para coordenadas da planta.

    Retorna ``(x_m, z_m, celula_idx)`` ou ``(None, None, None)`` quando a
    calibração é inválida/ausente ou o ponto cai fora da planta.
    """
    if not box_xyxy or not isinstance(box_xyxy, (list, tuple)) or len(box_xyxy) != 4:
        return None, None, None
    H = (calibracao or {}).get("H")
    if not H or len(H) != 3:
        return None, None, None
    try:
        x1, y1, x2, y2 = (float(v) for v in box_xyxy)
        u = (x1 + x2) / 2.0
        v = y2
        # Normaliza para o frame em que a H foi calculada (padrão: 720x480)
        frame = (calibracao or {}).get("frame") or {"w": FRAME_DETECTOR_W, "h": FRAME_DETECTOR_H}
        fw = float(frame.get("w", FRAME_DETECTOR_W) or FRAME_DETECTOR_W)
        fh = float(frame.get("h", FRAME_DETECTOR_H) or FRAME_DETECTOR_H)
        u_cal = u * (fw / FRAME_DETECTOR_W)
        v_cal = v * (fh / FRAME_DETECTOR_H)
        # Homografia 3x3 (px, py da planta 320x240) com normalização em w
        px = H[0][0] * u_cal + H[0][1] * v_cal + H[0][2]
        py = H[1][0] * u_cal + H[1][1] * v_cal + H[1][2]
        den = H[2][0] * u_cal + H[2][1] * v_cal + H[2][2]
        if abs(den) < 1e-9:
            return None, None, None
        px /= den
        py /= den
        x_m = (px / 320.0) * PLANTA_LARGURA_M - PLANTA_LARGURA_M / 2.0
        z_m = (py / 240.0) * PLANTA_ALTURA_M - PLANTA_ALTURA_M / 2.0
        col = int((x_m + PLANTA_LARGURA_M / 2.0) / CELULA_M)
        row = int((z_m + PLANTA_ALTURA_M / 2.0) / CELULA_M)
        col = max(0, min(MAPA_COLUNAS - 1, col))
        row = max(0, min(MAPA_LINHAS - 1, row))
        return round(x_m, 3), round(z_m, 3), row * MAPA_COLUNAS + col
    except (TypeError, ValueError, IndexError, ZeroDivisionError):
        return None, None, None


def _obter_calibracao():
    """Lê a calibração ativa em disco (sem cache para não servir H velha)."""
    try:
        return servidor._ler_calibracao()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Buffer circular de trajetória (Etapa 4 — replay real)
# ---------------------------------------------------------------------------
_TRAJETORIA_BUFFER = {}        # track_id -> deque(maxlen=30) de pontos
_ULTIMA_AMOSTRA_TRAJETORIA = {}  # track_id -> monotonic
_TRILHA_EM_EVENTO = {}         # track_id -> {"ocorrencia_id": int, "t_inicio": ms}
_ULTIMA_AMOSTRA_EXPOSICAO = None
_FLUSH_EXPOSICAO = 0.0
_ACUMULADO_EXPOSICAO = {}      # celula_idx -> [presenca_s, infracao_s, eventos]


def _ponto_trajetoria(op):
    return {
        "t_ms": int(time.monotonic() * 1000),
        "x_m": op.pos_x_m,
        "z_m": op.pos_z_m,
        "helmet": 1 if op.tem_capacete else 0,
        "vest": 1 if op.tem_colete else 0,
        "in_risk": 1 if op.risco_detectado else 0,
    }


def _amostrar_trajetoria(lista_operarios):
    """Amostra pontos de trajetória a no máximo 2 Hz (0.5 s), buffer de 30."""
    if not lista_operarios:
        return
    agora = time.monotonic()
    for op in lista_operarios:
        if getattr(op, "track_id", None) is None or op.pos_x_m is None or op.pos_z_m is None:
            continue
        ultima = _ULTIMA_AMOSTRA_TRAJETORIA.get(op.track_id, 0.0)
        if agora - ultima < 0.5:
            continue
        _ULTIMA_AMOSTRA_TRAJETORIA[op.track_id] = agora
        ponto = _ponto_trajetoria(op)
        buffer = _TRAJETORIA_BUFFER.setdefault(op.track_id, [])
        buffer.append(ponto)
        if len(buffer) > 30:
            buffer.pop(0)
        # Enquanto a trajetória está vinculada a um evento, os pontos novos
        # já vão direto ao banco (janela de +15 s após a ocorrência).
        evento = _TRILHA_EM_EVENTO.get(op.track_id)
        if evento and (ponto["t_ms"] - evento["t_inicio"]) <= 15000:
            try:
                banco.salvar_pontos_trajetoria(evento["ocorrencia_id"], [ponto])
            except Exception as exc:
                _registrar_falha(f"falha ao salvar ponto de trajetoria: {exc!r}")
        elif evento:
            _TRILHA_EM_EVENTO.pop(op.track_id, None)


def _vincular_trilha(track_id, ocorrencia_id):
    """Persiste o buffer recém-amostrado e marca a trilha como em evento."""
    pontos = list(_TRAJETORIA_BUFFER.get(track_id, []))
    if pontos:
        try:
            banco.salvar_pontos_trajetoria(ocorrencia_id, pontos)
        except Exception as exc:
            _registrar_falha(f"falha ao salvar buffer de trajetoria: {exc!r}")
    # Os pontos do buffer já estão gravados; limpá-lo evita gravar os mesmos
    # pontos de novo caso a mesma trilha gere outra ocorrência depois do cooldown.
    _TRAJETORIA_BUFFER[track_id] = []
    _TRILHA_EM_EVENTO[track_id] = {"ocorrencia_id": ocorrencia_id, "t_inicio": int(time.monotonic() * 1000)}


def _acumular_exposicao(lista_operarios):
    """Acumula presença/infração por célula e descarrega a cada ~1 s."""
    global _ULTIMA_AMOSTRA_EXPOSICAO, _FLUSH_EXPOSICAO
    agora = time.monotonic()
    if _ULTIMA_AMOSTRA_EXPOSICAO is None:
        _ULTIMA_AMOSTRA_EXPOSICAO = agora
        return
    dt = min(2.0, max(0.0, agora - _ULTIMA_AMOSTRA_EXPOSICAO))
    _ULTIMA_AMOSTRA_EXPOSICAO = agora
    if dt <= 0:
        return
    for op in lista_operarios:
        if op.celula_idx is None:
            continue
        acc = _ACUMULADO_EXPOSICAO.setdefault(op.celula_idx, [0.0, 0.0, 0])
        acc[0] += dt
        if classificar_infracao(op):
            acc[1] += dt
    if agora - _FLUSH_EXPOSICAO >= 1.0:
        _flush_exposicao(agora)


def _flush_exposicao(agora=None):
    """Grava o acumulado de exposição por célula no banco (se houver dados)."""
    global _ACUMULADO_EXPOSICAO, _FLUSH_EXPOSICAO
    agora = agora if agora is not None else time.monotonic()
    if not _ACUMULADO_EXPOSICAO:
        _FLUSH_EXPOSICAO = agora
        return
    incrementos = dict(_ACUMULADO_EXPOSICAO)
    _ACUMULADO_EXPOSICAO = {}
    _FLUSH_EXPOSICAO = agora
    try:
        banco.registrar_exposicao_celulas(incrementos)
    except Exception as exc:
        _registrar_falha(f"falha ao registrar exposicao: {exc!r}")


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------
def organizar_dado(specs_frame: dict, box_area_risco: tuple, area_risco_ativa: bool, frame=None):
    """Monta os operários do frame, associa EPIs, avalia risco e persiste.

    Cada etapa final (log e salvamento) é isolada: uma falha em
    ``analisar_seguranca`` não impede ``filtrar_salvamento`` de gravar a
    evidência, e vice-versa.
    """
    lista_operarios = []

    pessoas_detectadas = _get_pessoa(specs_frame)
    if not pessoas_detectadas:
        # Quadros vazios mantêm o cliente do Gêmeo informado de que a fonte
        # real continua conectada, em vez de parecer uma perda de sinal.
        _executar_seguro("telemetria_gemeo", servidor.enviar_telemetria, lista_operarios)
        return lista_operarios

    for dados_pessoa in pessoas_detectadas:
        novo_operario = Operario(
            box_xyxy=_to_xyxy(dados_pessoa, ["bounding_box_xyxy"], 0.0),
            conf_pessoa=_get_conf(dados_pessoa),
        )
        lista_operarios.append(novo_operario)

    # Cada EPI vai para UM operário e cada operário recebe no máximo UM EPI
    # de cada tipo (pareamento guloso por menor distância).
    for dado_epi, operario in _atribuir_epi(specs_frame.get("helmet") or [], lista_operarios, ZONA_CAPACETE):
        operario.tem_capacete = True
        operario.conf_capacete = _get_conf(dado_epi)
        operario.box_capacete = _to_xyxy(dado_epi, ["bounding_box_xyxy"], 0.0)

    for dado_epi, operario in _atribuir_epi(specs_frame.get("vest") or [], lista_operarios, ZONA_COLETE):
        operario.tem_colete = True
        operario.conf_colete = _get_conf(dado_epi)
        operario.box_colete = _to_xyxy(dado_epi, ["bounding_box_xyxy"], 0.0)

    if area_risco_ativa:
        for operario in lista_operarios:
            if verificar_area_risco(box_area_risco, operario.box_xyxy):
                operario.risco_detectado = True

    # Projeção do ponto dos pés para a planta (Etapa 3) — sem calibração
    # válida os campos ficam None e o banco grava NULL.
    calibracao = _obter_calibracao()
    if calibracao:
        for operario in lista_operarios:
            x_m, z_m, idx = projetar_pe_para_planta(operario.box_xyxy, calibracao)
            operario.pos_x_m, operario.pos_z_m, operario.celula_idx = x_m, z_m, idx

    _executar_seguro("analisar_seguranca", analisar_seguranca, lista_operarios)
    trilhas_antes = _proximo_track_id
    _executar_seguro("filtrar_salvamento", filtrar_salvamento, lista_operarios, frame)
    # Amostra o buffer de trajetória a no máximo 2 Hz e persiste os pontos
    # de trilhas já vinculadas a um evento (Etapa 4)
    _executar_seguro("trajetoria", _amostrar_trajetoria, lista_operarios)
    # Acumula presença/infração por célula para o mapa de calor (Etapa 5)
    _executar_seguro("exposicao", _acumular_exposicao, lista_operarios)
    # filtrar_salvamento atribui as trilhas; só então o payload contém o
    # track_id efêmero junto de caixas, EPIs, confiança e risco consolidados.
    _executar_seguro("telemetria_gemeo", servidor.enviar_telemetria, lista_operarios)
    # filtrar_salvamento associa as trilhas; as novas contam como passagens.
    _executar_seguro("amostragem", _amostrar, lista_operarios, bool(area_risco_ativa),
                     max(0, _proximo_track_id - trilhas_antes))
    return lista_operarios


def _amostrar(lista_operarios, area_ativa, trilhas_novas):
    """Conta quantas pessoas foram OBSERVADAS (denominador da taxa de conformidade).

    Roda a cada frame com pessoas, inclusive os conformes. Os contadores ficam em
    memória e só vão ao banco a cada ``INTERVALO_GRAVACAO`` s, com o pendrive montado."""
    amostragem.registrar(lista_operarios, area_ativa, trilhas_novas)
    if banco.pendrive_pronto():
        amostragem.descarregar(banco.CAMINHO_BANCO)


def _executar_seguro(nome, funcao, *args):
    """Executa uma etapa do pipeline sem deixar a exceção subir ao callback."""
    try:
        return funcao(*args)
    except Exception as exc:
        _registrar_falha(f"{nome} falhou: {exc!r}")
        return None


def _registrar_falha(mensagem: str):
    texto = f"[ERRO]: {mensagem}"
    print(texto)
    traceback.print_exc()
    try:
        servidor.enviar_log(texto)
    except Exception:
        pass  # o log para a interface nunca pode derrubar a deteccao


def _atribuir_epi(epis, operarios, corpo):
    """Pareia EPIs e operários de forma exclusiva (guloso por distância).

    1. gera todos os pares válidos ``(distância, idx_epi, idx_operario)`` — o
       centro do EPI precisa cair dentro da largura da pessoa e na faixa
       vertical ``corpo``;
    2. ordena por distância crescente;
    3. percorre a lista consumindo cada EPI e cada operário no máximo uma vez.

    Retorna uma lista de ``(dado_epi, operario)`` (``dado_epi`` é o dict
    original da detecção, de onde saem caixa e confiança).
    """
    boxes_epi = []
    for dado in epis:
        if not isinstance(dado, dict):
            boxes_epi.append(None)
            continue
        box = _to_xyxy(dado, ["bounding_box_xyxy"], 0.0)
        boxes_epi.append(None if box == [0.0, 0.0, 0.0, 0.0] else box)

    boxes_op = []
    for operario in operarios:
        box = list(operario.box_xyxy)
        boxes_op.append(None if box == [0.0, 0.0, 0.0, 0.0] else box)

    pares = []
    for idx_epi, box_epi in enumerate(boxes_epi):
        if box_epi is None:
            continue
        centro_epi = calcular_centro(box_epi)
        for idx_op, box_op in enumerate(boxes_op):
            if box_op is None:
                continue
            if verificar_epi(box_epi, box_op, corpo):
                distancia = math.dist(centro_epi, calcular_centro(box_op))
                pares.append((distancia, idx_epi, idx_op))

    pares.sort()

    epis_usados = set()
    operarios_usados = set()
    atribuicoes = []
    for _distancia, idx_epi, idx_op in pares:
        if idx_epi in epis_usados or idx_op in operarios_usados:
            continue
        epis_usados.add(idx_epi)
        operarios_usados.add(idx_op)
        atribuicoes.append((epis[idx_epi], operarios[idx_op]))

    return atribuicoes


ultimo_alerta = 0.0
TEMPO_ESPERA = config.TEMPO_ESPERA


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

LIMIAR_IOU = config.LIMIAR_IOU                # IoU minimo para considerar a mesma trajetoria
LIMIAR_DISTANCIA = config.LIMIAR_DISTANCIA   # fracao da menor diagonal entre as duas caixas
MARGEM_AMBIGUIDADE = config.MARGEM_AMBIGUIDADE  # diferenca minima de placar para descartar empate
TEMPO_ESPERA_SALVAR = config.TEMPO_ESPERA_SALVAR  # cooldown POR trilha e POR tipo de infracao
# A trilha vive pelo menos tanto quanto o cooldown: se a pessoa some atras de
# um obstaculo e volta antes do cooldown acabar, mantem o mesmo track_id e nao
# gera ocorrencia duplicada.
TEMPO_VIDA_TRILHA = float(config.TEMPO_VIDA_TRILHA)

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
    """Atribui um ``track_id`` efemero a cada operario do frame atual.

    Atribuicao GLOBAL gulosa (Etapa 6 do Plano de Evolucao): pontua TODOS os
    pares (trilha, operario) compativeis, ordena do melhor placar para o pior
    (e, em empate, prioriza trilhas vistas a no maximo 3 s) e atribui de forma
    gulosa — cada trilha e cada operario usados no maximo uma vez. Em
    cruzamentos a ordem da lista nao decide identidade: vence o par global
    mais forte. A regra de ambiguidade continua valendo: se o melhor e o
    segundo candidato empatarem (diferenca < MARGEM_AMBIGUIDADE), o operario
    nao recebe trilha nenhuma e abre uma nova.
    """
    global _proximo_track_id, _trilhas_ativas

    for trilha_id in list(_trilhas_ativas.keys()):
        if (agora - _trilhas_ativas[trilha_id]["visto_em"]) > TEMPO_VIDA_TRILHA:
            del _trilhas_ativas[trilha_id]

    candidatas = list(_trilhas_ativas.items())

    # 1) pontua cada par (trilha, operario) compativel
    candidatos = []
    for indice_op, operario in enumerate(lista_de_operarios):
        compativeis = []
        for trilha_id, dados in candidatas:
            pontos = pontuar_associacao(operario.box_xyxy, dados["box"])
            if pontos is None:
                continue
            compativel = (
                pontos["iou"] >= LIMIAR_IOU
                or pontos["distancia_relativa"] <= LIMIAR_DISTANCIA
            )
            if compativel:
                compativeis.append((trilha_id, pontos, dados))
        compativeis.sort(key=lambda item: item[1]["placar"], reverse=True)
        # 2) cruzamento ambiguo (duas trilhas praticamente empatadas): nao
        #    presumimos identidade e descartamos as candidaturas do operario;
        #    ele vai abrir uma trilha nova.
        if (
            len(compativeis) >= 2
            and abs(compativeis[0][1]["placar"] - compativeis[1][1]["placar"]) < MARGEM_AMBIGUIDADE
        ):
            continue
        for trilha_id, pontos, dados in compativeis:
            # dt <= 3 s: trilha "fresca"; desempata placares iguais contra
            # trilhas paradas ha mais tempo (o TTL segue valendo so para expirar).
            fresca = 1.0 if (agora - dados["visto_em"]) <= 3.0 else 0.0
            candidatos.append((pontos["placar"], fresca, trilha_id, indice_op))

    # 3) guloso global: do melhor placar para o pior; trilha e operario no maximo uma vez
    candidatos.sort(key=lambda item: (item[0], item[1]), reverse=True)
    trilhas_usadas = set()
    atribuicoes = {}
    for _placar, _fresca, trilha_id, indice_op in candidatos:
        if trilha_id in trilhas_usadas or indice_op in atribuicoes:
            continue
        trilhas_usadas.add(trilha_id)
        atribuicoes[indice_op] = trilha_id

    for indice_op, operario in enumerate(lista_de_operarios):
        trilha_id = atribuicoes.get(indice_op)
        if trilha_id is None:
            trilha_id = _proximo_track_id
            _proximo_track_id += 1
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
            "conf_pessoa": _to_float(outro.conf_pessoa, None),
            "conf_capacete": _to_float(outro.conf_capacete, None),
            "conf_colete": _to_float(outro.conf_colete, None),
            "pessoa": list(outro.box_xyxy),
            "capacete": list(outro.box_capacete) if outro.box_capacete else None,
            "colete": list(outro.box_colete) if outro.box_colete else None,
        })
    return cena


def filtrar_salvamento(lista_de_operarios, frame=None):
    """Avalia CADA pessoa do frame individualmente e persiste as infracoes.

    Diferencas em relacao ao cooldown global anterior:

    * uma pessoa em conformidade nunca zera o registro de outra irregular;
    * duas pessoas diferentes nunca se bloqueiam entre si;
    * a repeticao e controlada por (track_id, tipo_infracao);
    * um unico arquivo .jpg e gravado por cena, mesmo com varios registros.
    """
    agora = time.time()
    if not lista_de_operarios:
        return []

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
        return []

    # Lib antiga / stubs de teste: sem frame nao ha foto para persistir,
    # mas o restante do fluxo (trilhas, cooldown) continua.
    if frame is None:
        return []

    registros = [
        {
            "tipo_infracao": tipo,
            "posicao_operario": list(operario.box_xyxy),
            "conf_pessoa": _to_float(operario.conf_pessoa, None),
            "conf_capacete": _to_float(operario.conf_capacete, None),
            "conf_colete": _to_float(operario.conf_colete, None),
            "box_capacete": list(operario.box_capacete) if operario.box_capacete else None,
            "box_colete": list(operario.box_colete) if operario.box_colete else None,
            "x_m": operario.pos_x_m,
            "z_m": operario.pos_z_m,
            "celula_idx": operario.celula_idx,
        }
        for operario, tipo in aprovados
    ]

    salvos = banco.salvar_cena(frame, registros, montar_cena(lista_de_operarios))

    # Vincula a trilha de cada trabalhador salvo à ocorrência correspondente;
    # a trajetória persiste junto com a evidência e o mapa de calor acumulado
    # é descarregado neste mesmo ciclo (Etapas 4 e 5).
    if salvos:
        for (operario, tipo), ocorrencia_id in zip(aprovados, salvos):
            _vincular_trilha(operario.track_id, ocorrencia_id)
        _flush_exposicao()
        for operario, tipo in aprovados:
            _ultima_ocorrencia[(operario.track_id, tipo)] = agora

    # Limpa chaves antigas para o dicionario nao crescer sem limite.
    for chave in list(_ultima_ocorrencia.keys()):
        if (agora - _ultima_ocorrencia[chave]) > (TEMPO_ESPERA_SALVAR * 3):
            del _ultima_ocorrencia[chave]

    return salvos

# ---------------------------------------------------------------------------
# Geometria
# ---------------------------------------------------------------------------
def verificar_area_risco(box_risco, box_pessoa) -> bool:
    if not box_risco or not box_pessoa:
        return False

    px1, py1, px2, py2 = box_pessoa
    rx1, ry1, rx2, ry2 = box_risco
    # Ponto de contato com o piso: centro horizontal da caixa, base vertical (y2)
    px_base = (px1 + px2) / 2
    py_base = py2
    return rx1 <= px_base <= rx2 and ry1 <= py_base <= ry2


def verificar_epi(box_epi, box_operario, local_corpo) -> bool:
    ox1, oy1, ox2, oy2 = box_operario
    ex1, ey1, ex2, ey2 = box_epi
    altura = abs(oy1 - oy2)
    centro_x_epi = (ex1 + ex2) / 2
    centro_y_epi = (ey1 + ey2) / 2
    zona_topo = oy1 + local_corpo[0] * altura
    zona_base = oy1 + local_corpo[1] * altura
    return ox1 <= centro_x_epi <= ox2 and zona_topo <= centro_y_epi <= zona_base


# ---------------------------------------------------------------------------
# Callback da camera
# ---------------------------------------------------------------------------
def operario_detectado(specs_frame, frame=None):
    """Callback compativel com a lib nova (dict + frame) e a antiga (so dict).

    Toda a cadeia (organizacao, analise, salvamento) roda dentro do
    ``try/except``: o callback da camera nunca pode cair. Sem frame (lib antiga
    6735581) o fluxo continua, mas nenhuma foto e persistida.
    """
    try:
        # Atualiza o buffer do ultimo frame para o endpoint /snapshot
        if frame is not None:
            try:
                servidor.atualizar_ultimo_frame(frame)
            except Exception:
                pass  # nao pode quebrar o callback da camera
        return organizar_dado(specs_frame, servidor.box_risco, servidor.risco, frame)
    except Exception as exc:
        _registrar_falha(f"callback de deteccao falhou: {exc!r}")
        return []


def _operario_detectado_legado(specs_frame):
    """Wrapper de 1 argumento para a lib antiga (on_detect_all exige 1 arg)."""
    return operario_detectado(specs_frame, None)


try:
    deteccao.on_detect_all(operario_detectado)
except (TypeError, ValueError):
    # Lib antiga valida len(args) != 1 no registro: usa o wrapper legado.
    deteccao.on_detect_all(_operario_detectado_legado)
