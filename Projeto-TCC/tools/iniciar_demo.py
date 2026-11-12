"""iniciar_demo.py — Lançador de 1 clique do painel do TCC (Windows).

Papel do arquivo
----------------
Sobe, em um único processo e sem comandos manuais, o ambiente completo de
demonstração do projeto:

1. **banco de demonstração** (``tools/.demo/seguranca.db``) pré-populado — criado
   só quando a tabela ainda está vazia:
   - usuário ``admin`` / senha ``admin123``;
   - 5 ocorrências variadas (sem capacete, sem colete, invasão de área de risco,
     uma confirmada e uma descartada) com ``x_m``, ``z_m`` e ``celula_idx``;
   - trajetória de ±15 s por ocorrência na tabela ``trajetoria`` (Replay 3D
     imediato na tela de ocorrências);
   - exposição por célula (``exposicao_celula``) para o mapa de calor;
   - amostras por minuto (``amostras_minuto``) para a conformidade Pessoa-Frame,
     os KPIs e a série diária do painel;
   - fotos de evidência JPEG geradas com Pillow (caixas de pessoa/EPI desenhadas).
2. **simulador WebSocket** ``tools/ws_teste_gemeo.py`` em subprocesso, em
   ``ws://localhost:8000/ws``, para o gêmeo 3D receber telemetria ao vivo;
3. **servidor web REAL** (``python/servidor.py``) em ``http://127.0.0.1:8765``,
   servindo os assets REAIS e todas as rotas REST. Como o Windows não tem a
   placa UNO Q, ``arduino.app_bricks.web_ui.WebUI`` é substituído por uma versão
   local compatível (mesma API: ``expose_api``/``on_message``/``send_message``)
   montada sobre FastAPI/Starlette + socket.io;
4. **mock silencioso da câmera** em ``http://127.0.0.1:4912/embed`` para o iframe
   "Ao vivo" não acusar erro de conexão sem câmera física;
5. **navegador** aberto automaticamente e encerramento limpo (servidor + WS) no
   ``Ctrl+C``.

Uso
---
    python tools\\iniciar_demo.py              # sobe, abre o navegador e espera
    python tools\\iniciar_demo.py --verificar   # sobe, testa as rotas e encerra
    python tools\\iniciar_demo.py --sem-navegador

Requisitos (ambiente do projeto): Python ≥ 3.10, fastapi, uvicorn, starlette,
python-socketio, websockets e Pillow.

O banco de produção (``/app/pendrive``) NUNCA é tocado: tudo fica em
``tools/.demo/`` (fora do Git), que pode ser apagado a qualquer momento — o
próximo start recria do zero.
"""
import asyncio
import inspect
import json
import math
import os
import random
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import types
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

# ===== 1. CONSTANTES E CAMINHOS =====
RAIZ_PROJETO = Path(__file__).resolve().parents[1]
PYTHON_DIR = RAIZ_PROJETO / "python"
ASSETS_DIR = RAIZ_PROJETO / "assets"
WS_SCRIPT = RAIZ_PROJETO / "tools" / "ws_teste_gemeo.py"

DEMO_DIR = RAIZ_PROJETO / "tools" / ".demo"
DB_PATH = DEMO_DIR / "seguranca.db"
FOTOS_DIR = DEMO_DIR / "evidencias"
WS_LOG = DEMO_DIR / "ws_teste.log"

PORTA_WEB = 8765
PORTA_WS = 8000
PORTA_CAMERA = 4912
URL_WEB = f"http://127.0.0.1:{PORTA_WEB}"

SENHA_DEMO = "admin123"
USUARIO_DEMO = "admin"

# Grade do mapa de calor (mesmos números de python/detector.py)
COLUNAS_GRADE = 80
LINHAS_GRADE = 60
CELULA_M = 0.5
MUNDO_LARGURA = 40.0
MUNDO_PROFUNDIDADE = 30.0

# Estado preenchido em montar_ambiente()/encerrar()
banco = None
amostragem = None
servidor = None
_calibracao_criada = False


def _log(mensagem):
    """Impressão com prefixo único (o terminal fica limpo e legível)."""
    print(f"[DEMO] {mensagem}", flush=True)


# =========================================================================
# 2. AMBIENTE: hash de senha, stub do UNO Q e importação dos módulos REAIS
# =========================================================================
def _preparar_ambiente():
    """Prepara ``sys.path``, o hash da senha e o stub de ``arduino.app_bricks``.

    O stub precisa existir ANTES de ``import servidor``: é ele que o
    ``servidor.py`` real usa para registrar rotas (``expose_api``) e mensagens
    (``on_message``). As funções de negócio continuam 100 % do projeto.
    """
    global banco, amostragem, servidor

    # Hash PBKDF2 da senha de demonstração (só existe nesta sessão).
    os.environ["TCC_SENHA_HASH"] = _hash_da_senha(SENHA_DEMO)

    if str(PYTHON_DIR) not in sys.path:
        sys.path.insert(0, str(PYTHON_DIR))

    _instalar_stub_arduino()

    # Servidor primeiro: o par servidor <-> banco tem importação circular; o
    # banco só usa o servidor em tempo de execução, e o servidor acessa
    # `banco.*` na importação — então a ordem servidor -> banco é a correta.
    import servidor as _servidor              # noqa: E402
    import banco as _banco                    # noqa: E402
    import amostragem as _amostragem          # noqa: E402

    banco, amostragem, servidor = _banco, _amostragem, _servidor

    # Aponta o banco REAL para o banco de demonstração (nada de produção).
    banco.CAMINHO_BANCO = str(DB_PATH)
    banco.PASTA_FOTOS = str(FOTOS_DIR)
    banco.CAMINHO_PENDRIVE = str(DEMO_DIR)

    return servidor.ui


def _hash_da_senha(senha):
    """Hash PBKDF2 (mesmo formato de ``seguranca.gerar_hash``) sem importar o módulo."""
    import hashlib
    import secrets

    try:
        from config import ITERACOES_PBKDF2
    except Exception:
        ITERACOES_PBKDF2 = 200000
    sal = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, ITERACOES_PBKDF2)
    return f"pbkdf2${ITERACOES_PBKDF2}${sal.hex()}${digest.hex()}"


def _instalar_stub_arduino():
    """Cria ``arduino.app_bricks.web_ui.WebUI`` em memória (sem tocar no disco).

    O substituto guarda o que o ``servidor.py`` registra e só depois é ligado ao
    app Starlette/socket.io montado em :func:`montar_servidor`.
    """
    if "arduino.app_bricks.web_ui" in sys.modules:
        return

    class WebUI:
        """Substituto local do WebUI da placa (mesma superfície de API)."""

        def __init__(self):
            self.rotas = []        # (metodo, caminho, funcao)
            self.mensagens = {}    # evento -> funcao
            self.sio = None        # servidor socket.io (definido depois)
            self.loop = None       # event loop do uvicorn (definido depois)

        def expose_api(self, metodo, caminho, funcao):
            """Registra uma rota REST (equivalente ao ``expose_api`` da placa)."""
            self.rotas.append((metodo.upper(), caminho, funcao))

        def on_message(self, evento, funcao):
            """Registra um handler de mensagem do frontend (WebSocket)."""
            self.mensagens[evento] = funcao

        def send_message(self, evento, dados):
            """Emite uma mensagem para os clientes conectados (silencioso se não houver)."""
            sio, loop = self.sio, self.loop
            if sio is None or loop is None:
                return
            try:
                asyncio.run_coroutine_threadsafe(sio.emit(evento, dados), loop)
            except Exception:
                pass

    pacote_arduino = types.ModuleType("arduino")
    pacote_arduino.__path__ = []                      # marca como pacote
    pacote_bricks = types.ModuleType("arduino.app_bricks")
    pacote_bricks.__path__ = []
    modulo_web_ui = types.ModuleType("arduino.app_bricks.web_ui")
    modulo_web_ui.WebUI = WebUI

    sys.modules["arduino"] = pacote_arduino
    sys.modules["arduino.app_bricks"] = pacote_bricks
    sys.modules["arduino.app_bricks.web_ui"] = modulo_web_ui


# =========================================================================
# 3. BANCO DE DEMONSTRAÇÃO (só semeia o que estiver vazio)
# =========================================================================
# Cada cena: tipo de infração (STRING CANONICA de detector.classificar_infracao —
# o assistente conta por nome exato), posição na planta (metros, origem no centro),
# confiança (pessoa/capacete/colete), caixas no frame 720x480 e status de revisão.
TIPOS = {
    "capacete": "Sem capacete",
    "colete": "Sem colete",
    "ambos": "Sem capacete e colete",
    "invasao": "Invasao de area de risco",
}

CENAS_DEMO = [
    {
        "tipo": TIPOS["capacete"],
        "x_m": -6.0, "z_m": 4.0,
        "status": "pendente", "motivo": None,
        "horas_atras": 2.5,
        "conf": (0.97, 0.28, 0.94),
        "risco": False,
        "caixas": {"pessoa": (196, 88, 468, 470), "capacete": (300, 40, 372, 104), "colete": (232, 180, 452, 392)},
        "cor": (248, 113, 113),
        "cena_id": "cena_demo_1",
        "colegas": [
            # Operário conforme: o detector real grava tipo_infracao=None (null no JSON)
            {"tipo_infracao": None, "conf": (0.95, 0.93, 0.91), "risco": False,
             "caixas": {"pessoa": (516, 104, 700, 470), "capacete": (578, 56, 640, 116), "colete": (540, 190, 676, 396)}},
        ],
    },
    {
        "tipo": TIPOS["colete"],
        "x_m": 7.5, "z_m": -3.0,
        "status": "pendente", "motivo": None,
        "horas_atras": 26.0,
        "conf": (0.95, 0.92, 0.24),
        "risco": False,
        "caixas": {"pessoa": (214, 96, 486, 470), "capacete": (318, 48, 388, 108), "colete": (244, 188, 456, 398)},
        "cor": (242, 183, 5),
        "cena_id": "cena_demo_2",
        "colegas": [],
    },
    {
        "tipo": TIPOS["invasao"],
        "x_m": -2.0, "z_m": -9.5,
        "status": "pendente", "motivo": None,
        "horas_atras": 50.0,
        "conf": (0.98, 0.95, 0.93),
        "risco": True,
        "caixas": {"pessoa": (250, 82, 512, 470), "capacete": (350, 34, 416, 96), "colete": (280, 176, 486, 392)},
        "cor": (248, 113, 113),
        "cena_id": "cena_demo_3",
        "colegas": [],
    },
    {
        "tipo": TIPOS["ambos"],
        "x_m": 3.0, "z_m": 5.5,
        "status": "pendente", "motivo": None,
        "horas_atras": 5.0,
        "conf": (0.96, 0.19, 0.22),
        "risco": False,
        "caixas": {"pessoa": (286, 76, 556, 470), "capacete": (388, 30, 454, 92), "colete": (316, 172, 526, 388)},
        "cor": (248, 113, 113),
        "cena_id": "cena_demo_6",
        "colegas": [],
    },
    {
        "tipo": TIPOS["capacete"],
        "x_m": 11.0, "z_m": 8.0,
        "status": "confirmada", "motivo": "Reincidência registrada em auditoria.",
        "horas_atras": 74.0,
        "conf": (0.96, 0.21, 0.9),
        "risco": False,
        "caixas": {"pessoa": (172, 92, 444, 470), "capacete": (276, 44, 344, 104), "colete": (208, 184, 428, 394)},
        "cor": (248, 113, 113),
        "cena_id": "cena_demo_4",
        "colegas": [],
    },
    {
        "tipo": TIPOS["colete"],
        "x_m": -13.0, "z_m": -6.0,
        "status": "descartada", "motivo": "Falso positivo: colete visível, oclusão parcial.",
        "horas_atras": 96.0,
        "conf": (0.93, 0.9, 0.33),
        "risco": False,
        "caixas": {"pessoa": (230, 100, 496, 470), "capacete": (332, 52, 400, 112), "colete": (258, 192, 470, 400)},
        "cor": (148, 163, 184),
        "cena_id": "cena_demo_5",
        "colegas": [],
    },
]


def _celula_idx(x_m, z_m):
    """Converte metros na planta (origem no centro) no índice da célula 80x60."""
    col = int((x_m + MUNDO_LARGURA / 2.0) / CELULA_M)
    linha = int((z_m + MUNDO_PROFUNDIDADE / 2.0) / CELULA_M)
    col = max(0, min(COLUNAS_GRADE - 1, col))
    linha = max(0, min(LINHAS_GRADE - 1, linha))
    return linha * COLUNAS_GRADE + col


def _contar(tabela):
    """Conta linhas de uma tabela auxiliar (0 se ainda não existir)."""
    conexao = None
    try:
        conexao = sqlite3.connect(str(DB_PATH))
        return int(conexao.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0])
    except sqlite3.Error:
        return 0
    finally:
        if conexao:
            conexao.close()


def garantir_dados_demo():
    """Cria o banco de demonstração e semeia apenas o que estiver vazio."""
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    FOTOS_DIR.mkdir(parents=True, exist_ok=True)

    # Esquema REAIS do projeto (migração + tabelas trajetoria/exposicao_celula).
    banco.inicializar_banco(str(DB_PATH))

    conexao = sqlite3.connect(str(DB_PATH))
    try:
        amostragem.criar_tabela(conexao)
        conexao.commit()
    finally:
        conexao.close()

    _semear_ocorrencias()
    _semear_trajetorias()
    _semear_exposicao()
    _semear_amostras()
    _garantir_calibracao()


def _inserir_ocorrencia(cena):
    """Grava uma ocorrência da cena e devolve o id criado (usa o schema do banco)."""
    quando = datetime.now() - timedelta(hours=cena["horas_atras"])
    x_m, z_m = cena["x_m"], cena["z_m"]
    celula = _celula_idx(x_m, z_m)
    caixas = _montar_caixas(cena)
    nome_foto = f"foto_demo_{cena['cena_id'].split('_')[-1]}.jpg"

    conexao = sqlite3.connect(str(DB_PATH))
    try:
        cursor = conexao.cursor()
        cursor.execute(
            "INSERT INTO ocorrencias (timestamp, tipo_infracao, posicao_x, posicao_y,"
            " conf_pessoa, conf_capacete, conf_colete, caminho_foto, caixas, x_m, z_m, celula_idx,"
            " status, motivo, revisado_em)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                quando.strftime("%Y-%m-%dT%H:%M:%S"),
                cena["tipo"],
                float(caixas["pessoa"][0]),
                float(caixas["pessoa"][1]),
                cena["conf"][0], cena["conf"][1], cena["conf"][2],
                nome_foto,
                json.dumps(caixas, ensure_ascii=False),
                x_m, z_m, celula,
                cena["status"], cena["motivo"],
                quando.strftime("%Y-%m-%dT%H:%M:%S") if cena["status"] != "pendente" else None,
            ),
        )
        conexao.commit()
        return int(cursor.lastrowid), quando
    finally:
        conexao.close()


def _caixas_da_cena(cena):
    """Caixas coerentes com a infração: sem capacete não desenha capacete (e vice-versa)."""
    tipo = cena["tipo"].lower()
    caixa = cena["caixas"]
    return {
        "pessoa": list(caixa["pessoa"]),
        "capacete": None if "capacete" in tipo else (list(caixa["capacete"]) if "capacete" in caixa else None),
        "colete": None if "colete" in tipo else (list(caixa["colete"]) if "colete" in caixa else None),
    }


def _montar_caixas(cena):
    """Monta o JSON de caixas igual ao de ``banco._montar_caixas`` (pessoa + cena)."""
    # track_id estável (o hash de str varia entre processos por causa do PYTHONHASHSEED)
    base = int(cena["cena_id"].split("_")[-1])
    principal = _caixas_da_cena(cena)

    operarios = [{
        "track_id": f"demo_{base}",
        "tipo_infracao": cena["tipo"],
        "risco_detectado": bool(cena["risco"]),
        "conf_pessoa": cena["conf"][0],
        "conf_capacete": cena["conf"][1],
        "conf_colete": cena["conf"][2],
        "pessoa": principal["pessoa"],
        "capacete": principal["capacete"],
        "colete": principal["colete"],
    }]
    for indice, colega in enumerate(cena["colegas"], start=1):
        operarios.append({
            "track_id": f"demo_{base + indice}",
            "tipo_infracao": colega["tipo_infracao"],
            "risco_detectado": bool(colega["risco"]),
            "conf_pessoa": colega["conf"][0],
            "conf_capacete": colega["conf"][1],
            "conf_colete": colega["conf"][2],
            "pessoa": list(colega["caixas"]["pessoa"]),
            "capacete": list(colega["caixas"]["capacete"]),
            "colete": list(colega["caixas"]["colete"]),
        })
    return {
        "pessoa": principal["pessoa"],
        "capacete": principal["capacete"],
        "colete": principal["colete"],
        "cena_id": cena["cena_id"],
        "operarios": operarios,
    }


def _semear_ocorrencias():
    """Cria as ocorrências de demonstração (uma vez) e as fotos de evidência."""
    if _contar("ocorrencias") > 0:
        return

    for cena in CENAS_DEMO:
        _gerar_evidencia(cena)
        _inserir_ocorrencia(cena)
    _log(f"{len(CENAS_DEMO)} ocorrências de demonstração criadas.")


def _gerar_evidencia(cena):
    """Desenha um JPEG 720x480 com as caixas da cena (evidência simulada)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return

    imagem = Image.new("RGB", (720, 480), (16, 24, 40))
    desenho = ImageDraw.Draw(imagem)
    desenho.rectangle([0, 300, 720, 480], fill=(24, 34, 52))
    for x in range(0, 760, 48):
        desenho.line([(x, 300), (x - 70, 480)], fill=(31, 43, 63), width=1)
    desenho.rectangle([40, 40, 680, 300], outline=(40, 54, 78), width=2)

    caixas = _caixas_da_cena(cena)
    for chave, cor in (("pessoa", (56, 189, 248)), ("capacete", cena["cor"]), ("colete", (56, 189, 248))):
        caixa = caixas.get(chave)
        if not caixa:
            continue
        desenho.rectangle(list(caixa), outline=cor, width=3)
        desenho.text((caixa[0] + 4, max(2, caixa[1] - 14)), chave.upper(), fill=cor)

    for colega in cena["colegas"]:
        for chave, cor in (("pessoa", (56, 189, 248)), ("capacete", (74, 222, 128)), ("colete", (56, 189, 248))):
            caixa = colega["caixas"].get(chave)
            if caixa:
                desenho.rectangle(list(caixa), outline=cor, width=2)

    desenho.text((16, 14), "EVIDENCIA DE DEMONSTRACAO (CENA SIMULADA)", fill=(148, 163, 184))
    desenho.text((16, 450), f"{cena['tipo']} - {cena['status']}", fill=cena["cor"])

    nome = f"foto_demo_{cena['cena_id'].split('_')[-1]}.jpg"
    try:
        imagem.save(str(FOTOS_DIR / nome), format="JPEG", quality=82)
    except OSError as erro:
        _log(f"Aviso: não foi possível gerar a foto {nome}: {erro}")


def _semear_trajetorias():
    """Cria ±15 s de trajetória (1 Hz) para cada ocorrência sem pontos."""
    ids = _ids_sem_trajetoria()
    if not ids:
        return

    conexao = sqlite3.connect(str(DB_PATH))
    try:
        conexao.row_factory = sqlite3.Row
        linhas = {linha["id"]: linha for linha in conexao.execute("SELECT * FROM ocorrencias")}
    finally:
        conexao.close()

    total = 0
    for oid in ids:
        linha = linhas.get(oid)
        if not linha:
            continue
        pontos = _trajetoria_da_ocorrencia(linha)
        if banco.salvar_pontos_trajetoria(oid, pontos):
            total += len(pontos)
    _log(f"{total} pontos de trajetória (±15 s) gravados para o Replay 3D.")


def _ids_sem_trajetoria():
    """Ids de ocorrências que ainda não têm trajetória persistida."""
    conexao = sqlite3.connect(str(DB_PATH))
    try:
        return [int(linha[0]) for linha in conexao.execute(
            "SELECT o.id FROM ocorrencias o"
            " WHERE NOT EXISTS (SELECT 1 FROM trajetoria t WHERE t.ocorrencia_id = o.id)"
            " ORDER BY o.id"
        ).fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conexao.close()


def _trajetoria_da_ocorrencia(linha):
    """Gera 31 pontos (t-15 s … t+15 s) coerentes com a infração da ocorrência."""
    aleatorio = random.Random(1000 + int(linha["id"]))
    centro_x = float(linha["x_m"] or 0.0)
    centro_z = float(linha["z_m"] or 0.0)
    tipo = linha["tipo_infracao"] or ""
    try:
        momento = datetime.strptime(str(linha["timestamp"]), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        momento = datetime.now()
    t0 = int(momento.timestamp() * 1000)

    pontos = []
    for passo in range(-15, 16):
        minusculo = tipo.lower()
        if "e colete" in minusculo:
            capacete, colete = False, False
        elif "capacete" in minusculo:
            capacete, colete = (passo % 9 != 0), True
        elif "colete" in minusculo:
            capacete, colete = True, (passo % 11 != 0)
        else:
            capacete, colete = True, True
        pontos.append({
            "track_id": f"demo_{linha['id']}",
            "t_ms": t0 + passo * 1000,
            "x_m": round(centro_x + 1.6 * math.cos(passo * 0.35) + aleatorio.uniform(-0.15, 0.15), 3),
            "z_m": round(centro_z + 1.2 * math.sin(passo * 0.35) + aleatorio.uniform(-0.15, 0.15), 3),
            "helmet": int(capacete),
            "vest": int(colete),
            "in_risk": int("invas" in tipo and passo > -3),
            "fonte": "demo",
        })
    return pontos


def _semear_exposicao():
    """Cria o mapa de calor (células ao redor das ocorrências + fundo)."""
    if _contar("exposicao_celula") > 0:
        return

    aleatorio = random.Random(20240517)
    incrementos = {}
    for cena in CENAS_DEMO:
        centro = _celula_idx(cena["x_m"], cena["z_m"])
        col_centro, linha_centro = centro % COLUNAS_GRADE, centro // COLUNAS_GRADE
        for desloc_col in range(-4, 5):
            for desloc_linha in range(-4, 5):
                col = col_centro + desloc_col
                linha = linha_centro + desloc_linha
                if not (0 <= col < COLUNAS_GRADE and 0 <= linha < LINHAS_GRADE):
                    continue
                perto = abs(desloc_col) <= 1 and abs(desloc_linha) <= 1
                presenca = round(180 + aleatorio.random() * 420, 1)
                infracao = round(presenca * (0.35 if perto else 0.07), 1)
                eventos = 1 if perto else 0
                incrementos[linha * COLUNAS_GRADE + col] = (presenca, infracao, eventos)

    for _ in range(160):   # fundo: corredores com passagem regular
        idx = aleatorio.randrange(COLUNAS_GRADE * LINHAS_GRADE)
        incrementos[idx] = (round(60 + aleatorio.random() * 200, 1), round(aleatorio.random() * 10, 1), 0)

    if banco.registrar_exposicao_celulas(incrementos):
        _log(f"Mapa de calor semeado: {len(incrementos)} células com exposição.")


def _semear_amostras():
    """Cria amostras por minuto dos últimos 7 dias (conformidade e série diária)."""
    if _contar("amostras_minuto") > 0:
        return

    aleatorio = random.Random(99001)
    agora = datetime.now()
    linhas = []
    for dia in range(7):
        data = (agora - timedelta(days=dia)).date()
        for hora in (8, 11, 14, 17):
            pessoas = aleatorio.randint(90, 220)
            com_capacete = int(pessoas * aleatorio.uniform(0.86, 0.97))
            com_colete = int(pessoas * aleatorio.uniform(0.9, 0.99))
            conformes = int(pessoas * aleatorio.uniform(0.8, 0.94))
            risco_ativo = aleatorio.randint(20, 70)
            em_risco = int(risco_ativo * aleatorio.uniform(0.05, 0.35))
            linhas.append((
                f"{data.isoformat()}T{hora:02d}:00", pessoas, com_capacete, com_colete,
                conformes, risco_ativo, em_risco, aleatorio.randint(0, 4),
            ))

    conexao = sqlite3.connect(str(DB_PATH))
    try:
        conexao.executemany(
            "INSERT INTO amostras_minuto (minuto, pessoas, com_capacete, com_colete,"
            " conformes, risco_ativo, em_risco, trilhas_novas)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(minuto) DO NOTHING",
            linhas,
        )
        conexao.commit()
    finally:
        conexao.close()
    _log(f"Amostras Pessoa-Frame semeadas: {len(linhas)} minutos (7 dias).")


def _garantir_calibracao():
    """Grava uma calibração de demonstração (só se o arquivo ainda não existir)."""
    global _calibracao_criada
    caminho = Path(servidor.CALIBRACAO_PATH)
    if caminho.exists():
        return
    dados = {
        "camId": "1A",
        "updatedAt": int(time.time() * 1000),
        "frame": {"w": 720, "h": 480},
        "img": {"w": 720, "h": 480},
        "plan": {"w": 320, "h": 240},
        "world": {"w": MUNDO_LARGURA, "d": MUNDO_PROFUNDIDADE},
        "H": [[320 / 720, 0.0, 0.0], [0.0, 240 / 480, 0.0], [0.0, 0.0, 1.0]],
        "origem": "lancador_demo",
    }
    try:
        caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        _calibracao_criada = True
        _log("Calibração de demonstração gravada (python/calibracao_gemeo.json).")
    except OSError as erro:
        _log(f"Aviso: calibração não gravada: {erro}")


# =========================================================================
# 4. SERVIDOR WEB — substituto do WebUI + rotas REAIS + socket.io + assets
# =========================================================================
class _JsonPronto(dict):
    """Resultado de ``request.json()`` utilizável com ``await`` e sem ``await``.

    O WebUI da placa entrega um ``json()`` síncrono; o Starlette entrega uma
    coroutine. Este dict "awaitável" atende os dois contratos sem alterar o
    ``servidor.py`` real.
    """

    def __await__(self):
        async def _pronto():
            return self
        return _pronto().__await__()


def _eh_request(parametro):
    """Diz se o parâmetro recebe o objeto de requisição (anotado ou chamado req)."""
    anotacao = parametro.annotation
    if anotacao is inspect.Parameter.empty:
        return parametro.name in ("req", "request")
    return getattr(anotacao, "__name__", "") in ("Request", "HTTPRequest")


def _converter(anotacao, bruto):
    """Converte um texto de query string para o tipo anotado (int/float/str)."""
    if anotacao in (int, float):
        try:
            return anotacao(bruto)
        except (TypeError, ValueError):
            return bruto
    return bruto


def _resposta_http(resultado):
    """Normaliza o retorno das rotas para uma resposta Starlette."""
    from starlette.responses import JSONResponse, PlainTextResponse, Response

    if isinstance(resultado, Response):
        return resultado
    if isinstance(resultado, tuple) and len(resultado) == 2 and isinstance(resultado[1], int):
        corpo, status = resultado
        if isinstance(corpo, Response):
            return corpo
        return JSONResponse(corpo, status_code=status)
    if isinstance(resultado, (dict, list)) or resultado is None:
        return JSONResponse(resultado)
    if isinstance(resultado, str):
        return PlainTextResponse(resultado)
    if isinstance(resultado, (bytes, bytearray)):
        return Response(bytes(resultado), media_type="application/octet-stream")
    return JSONResponse(resultado)


def _despachante(funcao):
    """Cria o endpoint Starlette que chama a função REAL registrada no WebUI."""
    assinatura = inspect.signature(funcao)

    async def endpoint(request):
        from starlette.requests import Request as Requisicao

        bruto = await request.body()

        async def _replay():
            return {"type": "http.request", "body": bruto, "more_body": False}

        pedido = Requisicao(request.scope, _replay)

        kwargs = {}
        for nome, parametro in assinatura.parameters.items():
            if parametro.kind in (parametro.VAR_POSITIONAL, parametro.VAR_KEYWORD):
                continue
            if nome in request.path_params:
                kwargs[nome] = request.path_params[nome]
            elif _eh_request(parametro):
                kwargs[nome] = pedido
            elif nome in request.query_params:
                kwargs[nome] = _converter(parametro.annotation, request.query_params[nome])

        if inspect.iscoroutinefunction(funcao):
            resultado = await funcao(**kwargs)
        else:
            resultado = funcao(**kwargs)
        return _resposta_http(resultado)

    return endpoint


def montar_servidor(ui):
    """Monta o app Starlette (rotas REAIS + assets) e o servidor socket.io."""
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route
    from starlette.staticfiles import StaticFiles

    rotas = [Route(caminho, _despachante(funcao), methods=[metodo])
             for metodo, caminho, funcao in ui.rotas]
    rotas.append(Mount("/", app=StaticFiles(directory=str(ASSETS_DIR), html=True), name="assets"))

    aplicacao = Starlette(routes=rotas)

    import socketio

    sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*",
                               logger=False, engineio_logger=False)
    ui.sio = sio
    for evento, funcao in ui.mensagens.items():
        sio.on(evento, _adaptar_mensagem(funcao))

    # Caminho /socket.io é do engine.io; o resto vai para o Starlette.
    asgi = socketio.ASGIApp(sio, aplicacao, socketio_path="socket.io")
    return asgi, sio


def _adaptar_mensagem(funcao):
    """Adapta o handler do projeto ao contrato do socket.io (``sid`` + dados)."""
    async def handler(sid, *dados):
        try:
            resultado = funcao(None, *dados)
            if inspect.isawaitable(resultado):
                await resultado
        except Exception:
            traceback.print_exc()
    return handler


def iniciar_servidor_web(ui):
    """Sobe o uvicorn em thread e devolve (servidor, thread, ui)."""
    import uvicorn

    asgi, sio = montar_servidor(ui)
    configuracao = uvicorn.Config(asgi, host="127.0.0.1", port=PORTA_WEB,
                                  log_level="warning", access_log=False)

    class _ServerComLoop(uvicorn.Server):
        """Server que publica o loop em execução para os envios de mensagem."""
        async def serve(self, sockets=None):
            ui.loop = asyncio.get_running_loop()
            return await super().serve(sockets=sockets)

    uv_server = _ServerComLoop(configuracao)

    def _rodar():
        try:
            uv_server.run()
        except Exception:
            traceback.print_exc()

    thread = threading.Thread(target=_rodar, name="uvicorn-demo", daemon=True)
    thread.start()
    return uv_server, thread, ui


def aguardar_pronto(timeout=25.0):
    """Espera o servidor responder (401/403/200 em /sessao) antes de abrir o navegador."""
    fim = time.time() + timeout
    while time.time() < fim:
        try:
            with urlopen(f"{URL_WEB}/sessao", timeout=1.0) as resposta:
                return True
        except HTTPError as erro:
            return erro.code in (200, 401, 403)
        except (URLError, OSError, TimeoutError):
            time.sleep(0.2)
    return False


# =========================================================================
# 5. MOCK SILENCIOSO DA CÂMERA (:4912/embed)
# =========================================================================
PAGINA_EMBED = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Câmera 01 — demonstração</title>
<style>
  html,body{margin:0;height:100%;background:#0b1220;color:#94a3b8;
    font-family:system-ui,Segoe UI,sans-serif;display:grid;place-items:center}
  .feed{position:relative;width:100%;height:100%;display:grid;place-items:center;
    background:radial-gradient(circle at 50% 40%,#16233a 0%,#0b1220 70%)}
  .scan{position:absolute;inset:0;background:repeating-linear-gradient(
    to bottom,rgba(148,163,184,.06) 0 2px,transparent 2px 4px)}
  .alvo{position:relative;text-align:center}
  .tag{display:inline-block;margin-bottom:10px;padding:4px 10px;border:1px solid #38bdf8;
    border-radius:999px;color:#38bdf8;font:600 12px/1.4 ui-monospace,monospace;letter-spacing:.08em}
  h1{margin:6px 0;font-size:clamp(18px,3vw,30px);color:#e2e8f0}
  p{margin:0;font-size:13px}
  .rec{position:absolute;top:14px;left:16px;display:flex;gap:8px;align-items:center;
    color:#f87171;font:600 12px ui-monospace,monospace}
  .dot{width:9px;height:9px;border-radius:50%;background:#ef4444;animation:pulse 1.4s infinite}
  @keyframes pulse{50%{opacity:.25}}
  .cam{position:absolute;bottom:14px;right:16px;color:#64748b;font:12px ui-monospace,monospace}
</style></head>
<body><div class="feed"><div class="scan"></div>
  <div class="rec"><span class="dot"></span>REC · SIMULAÇÃO</div>
  <div class="alvo">
    <span class="tag">CÂMERA 01 · DEMONSTRAÇÃO</span>
    <h1>Sem placa física conectada</h1>
    <p>Esta é a imagem simulada do TCC. Use a aba <b>Gêmeo 3D</b> para ver a planta e os operários.</p>
  </div>
  <div class="cam">720×480 · 4912/embed</div>
</div></body></html>
"""


def iniciar_camera_mock():
    """Sobe um HTTP silencioso em :4912 para o iframe "Ao vivo" não dar erro."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):   # noqa: N802 (API do BaseHTTPRequestHandler)
            caminho = self.path.split("?")[0].rstrip("/") or "/"
            se_for_embed = caminho in ("/", "/embed", "/embed.html")
            if se_for_embed:
                corpo = PAGINA_EMBED.encode("utf-8")
                self.send_response(200)
            else:
                corpo = b""
                self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8" if se_for_embed else "text/plain")
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if corpo:
                self.wfile.write(corpo)

        def log_message(self, *argumentos):   # silêncio total no terminal
            return

    try:
        servidor_http = ThreadingHTTPServer(("127.0.0.1", PORTA_CAMERA), Handler)
    except OSError as erro:
        _log(f"Aviso: porta {PORTA_CAMERA} indisponível para a câmera simulada ({erro}).")
        return None
    threading.Thread(target=servidor_http.serve_forever, name="camera-demo", daemon=True).start()
    _log(f"Câmera simulada no ar em http://127.0.0.1:{PORTA_CAMERA}/embed")
    return servidor_http


# =========================================================================
# 6. SIMULADOR WEBSOCKET (subprocesso)
# =========================================================================
def iniciar_ws():
    """Sobe o ``tools/ws_teste_gemeo.py`` em subprocesso (ws://localhost:8000/ws)."""
    if not WS_SCRIPT.is_file():
        _log("Aviso: tools/ws_teste_gemeo.py não encontrado; o gêmeo 3D fica sem telemetria.")
        return None

    log = open(WS_LOG, "w", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        processo = subprocess.Popen(
            [sys.executable, str(WS_SCRIPT), str(PORTA_WS)],
            cwd=str(RAIZ_PROJETO), stdout=log, stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, creationflags=flags,
        )
    except OSError as erro:
        log.close()
        _log(f"Aviso: não foi possível subir o WebSocket de teste ({erro}).")
        return None

    time.sleep(1.2)
    if processo.poll() is not None:
        log.close()
        _log("Aviso: o WebSocket de teste encerrou na inicialização. Ver logs em "
             f"{WS_LOG.name} (instale 'websockets' se faltar).")
        return None

    _log(f"WebSocket de telemetria no ar em ws://localhost:{PORTA_WS}/ws")
    return processo


# =========================================================================
# 7. PAINEL, NAVEGADOR E ENCERRAMENTO
# =========================================================================
def _painel():
    """Imprime o resumo do ambiente (URL, senha, WebSocket, banco)."""
    linha = "=" * 74
    print()
    print(linha)
    print(" PAINEL DO TCC — MODO DEMONSTRAÇÃO (dados simulados, sem placa)")
    print(linha)
    print(f"  Sistema (navegador) .....: {URL_WEB}")
    print(f"  Usuário / senha .........: {USUARIO_DEMO} / {SENHA_DEMO}")
    print(f"  WebSocket ao vivo .......: ws://localhost:{PORTA_WS}/ws")
    print(f"  Câmera simulada .........: http://127.0.0.1:{PORTA_CAMERA}/embed")
    print(f"  Banco de demonstração ...: {DB_PATH}")
    print(f"  Evidências (fotos) ......: {FOTOS_DIR}")
    print("-" * 74)
    print("  O que testar: login -> Ocorrências (revisar/replay 3D) -> Painel")
    print("  (hoje/7/30 dias) -> Gêmeo 3D (Fonte: dados reais do WebSocket) ->")
    print("  Assistente de IA -> Ao vivo (câmera simulada).")
    print(f"  Para encerrar: Ctrl+C nesta janela.")
    print(linha)
    print()


def _verificar_rotas():
    """Check-up das rotas principais (usado por --verificar e no arranque)."""
    alvos = [
        ("GET", "/sessao", 401),
        ("GET", "/listar_ocorrencias", 200),
        ("GET", "/dashboard_dados?dias=7", 200),
        ("GET", "/mapa_calor", 200),
        ("GET", "/snapshot", 200),
    ]
    resultados = []
    for metodo, caminho, esperado in alvos:
        try:
            with urlopen(f"{URL_WEB}{caminho}", timeout=4.0) as resposta:
                ok = resposta.status == esperado
                resultados.append((caminho, resposta.status, ok))
        except HTTPError as erro:
            ok = erro.code == esperado
            resultados.append((caminho, erro.code, ok))
        except Exception as erro:
            resultados.append((caminho, f"erro: {erro}", False))
    return resultados


def _encerrar(uv_server, thread, processo_ws, camera, sio):
    """Encerra servidor, subprocesso e câmera simulada sem deixar processos órfãos."""
    _log("Encerrando...")

    if uv_server is not None:
        uv_server.should_exit = True
    if thread is not None:
        thread.join(timeout=6.0)

    if processo_ws is not None and processo_ws.poll() is None:
        try:
            processo_ws.terminate()
            processo_ws.wait(timeout=4)
        except Exception:
            try:
                processo_ws.kill()
            except Exception:
                pass

    if camera is not None:
        try:
            camera.shutdown()
            camera.server_close()
        except Exception:
            pass

    if _calibracao_criada:
        try:
            Path(servidor.CALIBRACAO_PATH).unlink(missing_ok=True)
        except OSError:
            pass

    _log("Tudo encerrado. Até logo!")


# =========================================================================
# 8. PONTO DE ENTRADA
# =========================================================================
def _argumentos():
    """Lê os poucos argumentos aceitos (sem dependências externas)."""
    return {
        "sem_navegador": "--sem-navegador" in sys.argv[1:],
        "verificar": "--verificar" in sys.argv[1:],
    }


def main():
    """Sobe o ambiente de demonstração e mantém a janela aberta até Ctrl+C."""
    opcoes = _argumentos()
    print()
    print("=" * 74)
    print(" INICIANDO O PAINEL DO TCC (demonstração) — aguarde...")
    print("=" * 74)

    ui = _preparar_ambiente()
    garantir_dados_demo()

    uv_server, thread, _ = iniciar_servidor_web(ui)

    if not aguardar_pronto():
        _log("ERRO: o servidor web não respondeu em "
             f"{URL_WEB} (porta {PORTA_WEB} ocupada?).")
        _encerrar(uv_server, thread, None, None, getattr(ui, "sio", None))
        return 1

    _log(f"Painel no ar: {URL_WEB}")
    camera = iniciar_camera_mock()
    processo_ws = iniciar_ws()

    if not opcoes["sem_navegador"]:
        try:
            webbrowser.open(URL_WEB)
            _log("Navegador aberto no painel.")
        except Exception:
            _log("Não foi possível abrir o navegador automaticamente; abra "
                 f"{URL_WEB} manualmente.")

    _painel()

    if opcoes["verificar"]:
        _log("Verificação das rotas principais:")
        tudo_ok = True
        for caminho, status, ok in _verificar_rotas():
            tudo_ok = tudo_ok and ok
            _log(f"  {'OK ' if ok else 'FALHA'} {caminho} -> {status}")
        _encerrar(uv_server, thread, processo_ws, camera, getattr(ui, "sio", None))
        return 0 if tudo_ok else 1

    try:
        while thread.is_alive() and not getattr(uv_server, "should_exit", False):
            time.sleep(0.4)
    except KeyboardInterrupt:
        print()
        _log("Ctrl+C recebido.")

    _encerrar(uv_server, thread, processo_ws, camera, getattr(ui, "sio", None))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        print("\nFalha ao iniciar a demonstração. Tire um print desta janela.")
        try:
            input("Pressione Enter para fechar...")
        except EOFError:
            pass
        sys.exit(1)