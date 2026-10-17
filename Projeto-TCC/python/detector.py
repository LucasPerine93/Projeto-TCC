from arduino.app_bricks.video_objectdetection import VideoObjectDetection
from arduino.app_peripherals.camera import Camera

from dataclasses import dataclass
import math
import time
import traceback

import servidor
import banco
import amostragem

camera = Camera(source=0, resolution=(720, 480), fps=10)
try:
    deteccao = VideoObjectDetection(
        camera=camera,
        debounce_sec=0,
        confidence=0.5,
        camera_preview=True,
    )
except TypeError:
    # Lib antiga (pin 6735581): sem camera_preview e sem frame no callback.
    deteccao = VideoObjectDetection(
        camera=camera,
        debounce_sec=0,
        confidence=0.5,
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


# Faixa vertical do corpo (fração da altura da caixa da pessoa, medida a
# partir do topo) onde cada EPI deve ter o seu centro.
ZONA_CAPACETE = (-0.15, 0.35)
ZONA_COLETE = (0.36, 0.80)


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

    _executar_seguro("analisar_seguranca", analisar_seguranca, lista_operarios)
    trilhas_antes = _proximo_track_id
    _executar_seguro("filtrar_salvamento", filtrar_salvamento, lista_operarios, frame)
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
TEMPO_ESPERA_SALVAR = 20   # cooldown POR trilha e POR tipo de infracao
# A trilha vive pelo menos tanto quanto o cooldown: se a pessoa some atras de
# um obstaculo e volta antes do cooldown acabar, mantem o mesmo track_id e nao
# gera ocorrencia duplicada.
TEMPO_VIDA_TRILHA = float(TEMPO_ESPERA_SALVAR)

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

    # Lib antiga / stubs de teste: sem frame nao ha foto para persistir,
    # mas o restante do fluxo (trilhas, cooldown) continua.
    if frame is None:
        return

    registros = [
        {
            "tipo_infracao": tipo,
            "posicao_operario": list(operario.box_xyxy),
            "conf_pessoa": _to_float(operario.conf_pessoa, None),
            "conf_capacete": _to_float(operario.conf_capacete, None),
            "conf_colete": _to_float(operario.conf_colete, None),
            "box_capacete": list(operario.box_capacete) if operario.box_capacete else None,
            "box_colete": list(operario.box_colete) if operario.box_colete else None,
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


# ---------------------------------------------------------------------------
# Geometria
# ---------------------------------------------------------------------------
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
