from fastapi.responses import FileResponse
from collections import Counter
from datetime import datetime, timedelta
import json
import math
import servidor
import amostragem
import sqlite3
import time
import os

"""O docker coloca todos os apps na pasta "/app" 
    quando montar a unidade de disco, ela deve ser 
    montada na pasta do projeto mas acessada por "/app" """

CAMINHO_PENDRIVE = "/app/pendrive" 

CAMINHO_BANCO = os.path.join(CAMINHO_PENDRIVE, "seguranca.db")
PASTA_FOTOS = os.path.join(CAMINHO_PENDRIVE, "evidencias")


def pendrive_pronto() -> bool:
    """Versão silenciosa de verificar_pendrive (sem log), para uso a cada frame."""
    return os.path.ismount(CAMINHO_PENDRIVE)


def verificar_pendrive(caminho_pendrive: str) -> bool:
    if os.path.ismount(caminho_pendrive):
        mensagem = "[SUCESSO]: Pendrive montado e pronto"
        print(mensagem)
        servidor.enviar_log(mensagem)
        return True
    else:
        mensagem = "[ERRO]: Pendrive não encontrado"
        print(mensagem)
        servidor.enviar_log(mensagem)
        return False


COLUNAS_NOVAS = {
    "caixas": "TEXT",
    # Revisão pelo técnico (nada é apagado: descartar = marcar como falso positivo).
    "status": "TEXT NOT NULL DEFAULT 'pendente'",
    "motivo": "TEXT",
    "revisado_em": "TEXT",
}
STATUS_VALIDOS = ("pendente", "confirmada", "descartada")


def _migrar_esquema(cursor):
    """Migração leve e idempotente: acrescenta colunas que faltem em bancos antigos."""
    existentes = [linha[1] for linha in cursor.execute("PRAGMA table_info(ocorrencias)")]
    for nome, definicao in COLUNAS_NOVAS.items():
        if nome not in existentes:
            cursor.execute(f"ALTER TABLE ocorrencias ADD COLUMN {nome} {definicao}")


def _abrir_banco():
    """Conexão com o esquema garantido (leituras antes da 1a infração não falham)."""
    conexao = sqlite3.connect(CAMINHO_BANCO)
    cursor = conexao.cursor()
    tabela = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ocorrencias'"
    ).fetchone()
    if tabela:
        _migrar_esquema(cursor)
        conexao.commit()
    return conexao


def inicializar_banco(caminho_banco: str) -> bool:
    """ Cria a conexão como None antes do try para não 
        dar erro fatal no finally 
        se a conexão não for estabelecida """
    
    conexao = None 
    try:
        conexao = sqlite3.connect(caminho_banco)
        cursor = conexao.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ocorrencias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                tipo_infracao TEXT NOT NULL,
                posicao_x REAL,
                posicao_y REAL,
                conf_pessoa REAL NULL,
                conf_capacete REAL NULL,
                conf_colete REAL NULL,
                caminho_foto TEXT,
                caixas TEXT
            )
        """)

        _migrar_esquema(cursor)

        conexao.commit()
        mensagem = "[BANCO]: Tabela de ocorrências pronta!"
        print(mensagem)
        servidor.enviar_log(mensagem)
        return True
    
    except sqlite3.Error as e:
        mensagem = f"[ERRO]: Falha no banco de dados | detalhes do erro: {e}"
        print(mensagem)
        servidor.enviar_log(mensagem)
        return False
    
    finally:
        if conexao:
            conexao.close()

def _to_float(val, default=0.0):
    """Converte ``val`` em ``float`` nativo ou devolve ``default``.

    Trata ``None``, ``bool``, ``int``, ``float``, strings (com virgula decimal),
    escalares NumPy (``np.floating``/``np.integer``) e ``np.ndarray`` de um
    unico elemento. Arrays maiores, listas, NaN e infinito retornam ``default``.
    """
    if val is None:
        return default

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


def _to_lista(valor, inteiro: bool = False):
    """Converte caixas/numéricos em ``list[float]`` (ou ``list[int]``) nativos,
    descartando NumPy e garantindo que o JSON foge do TypeError."""
    if valor is None:
        return None
    try:
        if hasattr(valor, "tolist"):
            valor = valor.tolist()
    except Exception:
        pass
    if isinstance(valor, (list, tuple)):
        itens = [_to_float(v, None) for v in valor]
        if any(v is None for v in itens):
            return None
        return [int(v) for v in itens] if inteiro else itens
    numero = _to_float(valor, None)
    if numero is None:
        return None
    return int(numero) if inteiro else numero


def _montar_caixas(posicao_operario, box_capacete, box_colete, cena=None, cena_id=None):
    """Caixas do trabalhador + lista completa da cena, num unico JSON.

    ``operarios`` recebe a lista de todos os trabalhadores vistos no frame
    (``cena``); quando nao ha cena registrada, sai como lista vazia. Assim o
    front-end consegue destacar, na mesma foto, os demais operarios do frame.
    """
    caixas = {
        "pessoa": _to_lista(posicao_operario, inteiro=True),
        "capacete": _to_lista(box_capacete, inteiro=True),
        "colete": _to_lista(box_colete, inteiro=True),
        "cena_id": cena_id,
        "operarios": list(cena) if cena else [],
    }
    return json.dumps(caixas)


def salvar_cena(frame, registros, cena=None):
    """Grava UMA foto por cena e cria uma ocorrencia para cada trabalhador.

    ``registros`` e uma lista de dicionarios com: tipo_infracao,
    posicao_operario, conf_pessoa, conf_capacete, conf_colete, box_capacete e
    box_colete. ``cena`` e a lista de todos os trabalhadores vistos no frame.

    Retrocompatibilidade: o esquema do SQLite nao muda. Cada ocorrencia continua
    com sua propria linha (posicao, confiancas e classificacao); o que muda e
    que varias linhas passam a compartilhar o mesmo ``caminho_foto`` e o campo
    ``caixas`` tambem passa a guardar a lista ``operarios`` da cena.
    """
    if not registros:
        return []

    if not (verificar_pendrive(CAMINHO_PENDRIVE) and inicializar_banco(CAMINHO_BANCO)):
        return []

    cena = cena or []
    os.makedirs(PASTA_FOTOS, exist_ok=True)

    agora = time.time()
    agora_ms = int(agora * 1000)  # ms: evita colisao de nome/id no mesmo segundo
    cena_id = f"cena_{agora_ms}"
    nome_imagem = f"foto_{agora_ms}_{registros[0]['tipo_infracao'].replace(' ', '_')}.jpg"
    caminho_salvar = os.path.join(PASTA_FOTOS, nome_imagem)

    try:
        with open(caminho_salvar, "wb") as arquivo:
            arquivo.write(frame)
    except OSError as erro:
        mensagem = f"[ERRO]: Falha ao gravar a evidencia | detalhes do erro: {erro}"
        print(mensagem)
        servidor.enviar_log(mensagem)
        return []

    conexao = None
    ids_criados = []
    try:
        conexao = sqlite3.connect(CAMINHO_BANCO)
        cursor = conexao.cursor()

        sql = """INSERT INTO ocorrencias (timestamp, tipo_infracao, posicao_x, posicao_y, conf_pessoa, conf_capacete, conf_colete, caminho_foto, caixas)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""

        for registro in registros:
            posicao = registro["posicao_operario"]
            px = (_to_float(posicao[0]) + _to_float(posicao[2])) / 2
            py = (_to_float(posicao[1]) + _to_float(posicao[3])) / 2
            caixas_json = _montar_caixas(
                posicao,
                registro.get("box_capacete"),
                registro.get("box_colete"),
                cena,
                cena_id,
            )
            cursor.execute(
                sql,
                (
                    time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(agora)),
                    registro["tipo_infracao"],
                    px,
                    py,
                    _to_float(registro.get("conf_pessoa"), None),  # None -> NULL
                    _to_float(registro.get("conf_capacete"), None),  # None -> NULL
                    _to_float(registro.get("conf_colete"), None),  # None -> NULL
                    caminho_salvar,
                    caixas_json,
                ),
            )
            ids_criados.append(cursor.lastrowid)

        conexao.commit()

    except sqlite3.Error as erro:
        if conexao:
            conexao.rollback()
        mensagem = f"[ERRO]: Falha no banco de dados | detalhes do erro: {erro}"
        print(mensagem)
        servidor.enviar_log(mensagem)
        ids_criados = []
    finally:
        if conexao:
            conexao.close()

    if ids_criados:
        mensagem = f"[SUCESSO]: Cena salva com {len(ids_criados)} ocorrencia(s)!"
        print(mensagem)
        servidor.enviar_log(mensagem)

    return ids_criados


def pegar_foto(nome_foto: str):
    caminho_foto = os.path.join(PASTA_FOTOS, os.path.basename(nome_foto))
    if os.path.exists(caminho_foto):
        return FileResponse(caminho_foto, media_type="image/jpeg") # Envia a foto
        
    return "Foto não encontrada"


def excluir_ocorrencia(ocorrencia_id):
    """Exclui uma ocorrência e sua evidência fotográfica de forma segura.

    A foto é removida somente de ``PASTA_FOTOS`` e somente após o commit da
    exclusão no SQLite. O retorno é serializável para a rota HTTP do WebUI.
    """
    try:
        ocorrencia_id = int(ocorrencia_id)
    except (TypeError, ValueError):
        return {"sucesso": False, "mensagem": "Identificador de ocorrência inválido."}

    conexao = None
    caminho_foto = None
    try:
        conexao = sqlite3.connect(CAMINHO_BANCO)
        cursor = conexao.cursor()
        registro = cursor.execute(
            "SELECT caminho_foto FROM ocorrencias WHERE id = ?", (ocorrencia_id,)
        ).fetchone()
        if registro is None:
            return {"sucesso": False, "mensagem": "Ocorrência não encontrada."}

        caminho_foto = registro[0]
        cursor.execute("DELETE FROM ocorrencias WHERE id = ?", (ocorrencia_id,))
        conexao.commit()
    except sqlite3.Error as erro:
        if conexao:
            conexao.rollback()
        mensagem = f"[ERRO]: Falha ao excluir ocorrência | detalhes do erro: {erro}"
        print(mensagem)
        servidor.enviar_log(mensagem)
        return {"sucesso": False, "mensagem": "Não foi possível excluir a ocorrência."}
    finally:
        if conexao:
            conexao.close()

    foto_excluida = False
    outras_referencias = 0
    if caminho_foto:
        caminho_seguro = os.path.join(PASTA_FOTOS, os.path.basename(caminho_foto))

        # Protecao de foto compartilhada: a mesma evidencia pode alimentar
        # varias ocorrencias da cena. O arquivo so sai do disco quando a
        # ultima referencia desaparecer. A comparacao usa o NOME DO ARQUIVO
        # (basename) para ignorar variacoes de caminho/separador que nao
        # mudam a identidade da evidencia.
        alvo = os.path.basename(caminho_seguro)
        conexao = None
        try:
            conexao = sqlite3.connect(CAMINHO_BANCO)
            cursor = conexao.cursor()
            caminhos = cursor.execute(
                "SELECT DISTINCT caminho_foto FROM ocorrencias"
            ).fetchall()
            outras_referencias = sum(
                1
                for (c,) in caminhos
                if c and os.path.basename(c) == alvo
            )
        except sqlite3.Error as erro:
            mensagem = f"[AVISO]: Nao foi possivel verificar referencias da foto: {erro}"
            print(mensagem)
            servidor.enviar_log(mensagem)
        finally:
            if conexao:
                conexao.close()

        if outras_referencias > 0:
            mensagem = (
                f"[BANCO]: Ocorrencia {ocorrencia_id} descartada; evidencia mantida "
                f"por ainda haver {outras_referencias} ocorrencia(s) na mesma foto."
            )
            print(mensagem)
            servidor.enviar_log(mensagem)
        else:
            try:
                if os.path.isfile(caminho_seguro):
                    os.remove(caminho_seguro)
                    foto_excluida = True
            except OSError as erro:
                mensagem = f"[AVISO]: Ocorrencia {ocorrencia_id} excluida, mas a foto nao pode ser removida: {erro}"
                print(mensagem)
                servidor.enviar_log(mensagem)

    mensagem = "Ocorrência descartada com sucesso."
    print(f"[BANCO]: {mensagem}")
    servidor.enviar_log(f"[BANCO]: {mensagem}")
    return {"sucesso": True, "mensagem": mensagem, "foto_excluida": foto_excluida}

def dados_ocorrencias():
    registros = []
    conexao = None
    # Sem banco ainda (pendrive ausente / nenhuma infração): lista vazia e SEM log,
    # porque a interface consulta isto de tempos em tempos.
    if not os.path.isfile(CAMINHO_BANCO):
        return registros
    try:
        conexao = _abrir_banco()
        if conexao.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ocorrencias'").fetchone() is None:
            return registros

        # Ativa o mapeamento por nome da coluna
        # Acessa tanto pelo indice como pelo nome
        conexao.row_factory = sqlite3.Row
        cursor = conexao.cursor()

        requisicao = "SELECT id, " \
                     "timestamp, " \
                     "tipo_infracao, " \
                     "posicao_x, " \
                     "posicao_y, " \
                     "conf_pessoa, " \
                     "conf_capacete, " \
                     "conf_colete, " \
                     "caminho_foto, " \
                     "caixas, " \
                     "COALESCE(status, 'pendente') AS status, " \
                     "motivo, " \
                     "revisado_em " \
                     "FROM ocorrencias " \
                     "ORDER BY id DESC"
        
        cursor.execute(requisicao)

        # Pega as linhas e converte para dicionarios 
        linhas = cursor.fetchall()
        registros = []
        for linha in linhas:
            registros.append(dict(linha))
        
        for foto in registros:
            """ Ao invés do caminho bruto da foto, pega só o nome do 
                arquivo para a interface web conseguir fazer o GET na
                função pegar foto """
            
            foto["caminho_foto"] = os.path.basename(foto["caminho_foto"]) 

    except sqlite3.Error as e:
        mensagem = f"[ERRO]: Falha no banco de dados | detalhes do erro: {e}"
        print(mensagem)
        servidor.enviar_log(mensagem)
    
    finally:
        if conexao:
            conexao.close()
    return registros

def revisar_ocorrencia(ocorrencia_id, status, motivo=""):
    """Registra a revisão do técnico. Nada é apagado: o descarte vira ``descartada``
    (falso positivo) e a foto permanece como evidência da decisão."""
    try:
        ocorrencia_id = int(ocorrencia_id)
    except (TypeError, ValueError):
        return {"sucesso": False, "mensagem": "Identificador de ocorrência inválido."}
    if status not in STATUS_VALIDOS:
        return {"sucesso": False, "mensagem": "Status inválido."}

    motivo = (motivo or "").strip()[:300]
    revisado_em = None if status == "pendente" else time.strftime("%Y-%m-%dT%H:%M:%S")
    conexao = None
    try:
        conexao = _abrir_banco()
        cursor = conexao.execute(
            "UPDATE ocorrencias SET status = ?, motivo = ?, revisado_em = ? WHERE id = ?",
            (status, motivo or None, revisado_em, ocorrencia_id),
        )
        conexao.commit()
        if cursor.rowcount == 0:
            return {"sucesso": False, "mensagem": "Ocorrência não encontrada."}
    except sqlite3.Error as erro:
        mensagem = f"[ERRO]: Falha ao revisar ocorrência | detalhes do erro: {erro}"
        print(mensagem)
        servidor.enviar_log(mensagem)
        return {"sucesso": False, "mensagem": "Não foi possível registrar a revisão."}
    finally:
        if conexao:
            conexao.close()

    return {"sucesso": True, "id": ocorrencia_id, "status": status,
            "motivo": motivo or None, "revisado_em": revisado_em}


def _limites_periodo(dias, agora=None):
    """Dias de calendário: ``dias=1`` é hoje desde 00:00; ``7`` são os 7 últimos dias
    incluindo hoje. Devolve (desde, ate, desde_anterior) como datetime."""
    agora = agora or datetime.now()
    dias = max(1, min(int(dias), 365))
    meia_noite = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    desde = meia_noite - timedelta(days=dias - 1)
    ate = meia_noite + timedelta(days=1)
    return desde, ate, desde - timedelta(days=dias)


def calcular_dados_dashboard(dias: int = 7):
    """Dados do painel. Mantém as chaves antigas e acrescenta o período, a
    conformidade (com denominador, vinda de ``amostragem``) e as contagens de revisão.

    Descartadas (falso positivo) não contam como ocorrência do período."""
    try:
        dias = int(dias)
    except (TypeError, ValueError):
        dias = 7
    desde, ate, desde_anterior = _limites_periodo(dias)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S")
    iso_min = lambda d: d.strftime("%Y-%m-%dT%H:%M")

    todos = dados_ocorrencias()
    do_periodo = [o for o in todos if iso(desde) <= (o["timestamp"] or "") < iso(ate)]
    validas = [o for o in do_periodo if o["status"] != "descartada"]

    por_tipo = dict(Counter(o["tipo_infracao"] for o in validas))
    contagem_status = Counter(o["status"] for o in do_periodo)

    resumo = {}
    anterior = {}
    try:
        if not os.path.isfile(CAMINHO_BANCO):
            raise FileNotFoundError("banco ainda nao existe")
        resumo = amostragem.resumo(CAMINHO_BANCO, iso_min(desde), iso_min(ate))
        anterior = amostragem.resumo(CAMINHO_BANCO, iso_min(desde_anterior), iso_min(desde))
    except FileNotFoundError:
        pass
    except Exception as erro:   # painel nunca cai por causa da amostragem
        print(f"[AVISO]: amostragem indisponível: {erro}")

    total = len(validas)
    return {
        "periodo": {"dias": dias, "desde": desde.date().isoformat(),
                    "ate": (ate - timedelta(days=1)).date().isoformat()},
        # --- chaves antigas (compatibilidade) ---
        "total_observacoes": total,
        "resumo_conformidade": por_tipo,
        "taxa_conformidade": {t: round(100 * n / total, 1) for t, n in por_tipo.items()} if total else {},
        "eventos_recentes": do_periodo,
        # --- novas ---
        "ocorrencias": {
            "total": total,
            "pendentes": contagem_status.get("pendente", 0),
            "confirmadas": contagem_status.get("confirmada", 0),
            "descartadas": contagem_status.get("descartada", 0),
        },
        "infracoes_por_tipo": por_tipo,
        "pessoas_observadas": resumo.get("pessoas_observadas", 0),
        "trilhas": resumo.get("trilhas", 0),
        "conformidade": resumo.get("conformidade"),
        "capacete": resumo.get("capacete"),
        "colete": resumo.get("colete"),
        "fora_de_risco": resumo.get("fora_de_risco"),
        "serie_diaria": resumo.get("serie_diaria", []),
        "anterior": {"conformidade": anterior.get("conformidade"),
                     "pessoas_observadas": anterior.get("pessoas_observadas", 0)},
    }
