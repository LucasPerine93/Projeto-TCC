from fastapi.responses import FileResponse
from collections import Counter
import json
import servidor
import sqlite3
import time
import os

"""O docker coloca todos os apps na pasta "/app" 
    quando montar a unidade de disco, ela deve ser 
    montada na pasta do projeto mas acessada por "/app" """

CAMINHO_PENDRIVE = "/app/pendrive" 

CAMINHO_BANCO = os.path.join(CAMINHO_PENDRIVE, "seguranca.db")
PASTA_FOTOS = os.path.join(CAMINHO_PENDRIVE, "evidencias")


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

        # Migração leve: garante a coluna de bounding boxes em bancos antigos.
        colunas_existentes = [
            linha[1] for linha in cursor.execute("PRAGMA table_info(ocorrencias)")
        ]
        if "caixas" not in colunas_existentes:
            cursor.execute("ALTER TABLE ocorrencias ADD COLUMN caixas TEXT")

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
        return [int(v) if inteiro else float(v) for v in valor]
    try:
        return int(valor) if inteiro else float(valor)
    except (TypeError, ValueError):
        return None


def _montar_caixas(posicao_operario, box_capacete, box_colete, cena=None, cena_id=None):
    """Caixas do trabalhador + lista completa da cena, num unico JSON.

    Exclusividade: quando não há cena registrada, ``operarios`` sai vazio em
    vez de servi-lo como repositório mutável — a lista só veIOS carregar no
    front-end conforme o cliente registra quais operários ficaram em risco na
   quele frame e a adere a essa copia.
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
    cena_id = f"cena_{int(agora)}"
    nome_imagem = f"foto_{int(agora)}_{registros[0]['tipo_infracao'].replace(' ', '_')}.jpg"
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
                [float(v) for v in posicao],
                _to_float(registro.get("box_capacete")),
                _to_float(registro.get("box_colete")),
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
                    _to_float(registro.get("conf_pessoa")),
                    _to_float(registro.get("conf_capacete")),
                    _to_float(registro.get("conf_colete")),
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


def salvar_ocorrencias(tipo_infracao, posicao_operario, conf_pessoa, conf_capacete, conf_colete, frame, box_capacete=None, box_colete=None, operarios_cena=None):
    """Persiste uma ocorrencia unica (mantido por retrocompatibilidade).

    Novos codigos devem preferir ``salvar_cena``, que grava uma unica foto
    quando varios trabalhadores aparecem irregulares no mesmo frame.
    """
    registro = {
        "tipo_infracao": tipo_infracao,
        "posicao_operario": posicao_operario,
        "conf_pessoa": conf_pessoa,
        "conf_capacete": conf_capacete,
        "conf_colete": conf_colete,
        "box_capacete": box_capacete,
        "box_colete": box_colete,
    }
    salvar_cena(frame, [registro], operarios_cena)

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
    try:
        conexao = sqlite3.connect(CAMINHO_BANCO)

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
                     "caixas " \
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

def calcular_dados_dashboard():
    dados = dados_ocorrencias() # Pega os dados do banco
    dados_totais = len(dados) # Lê o tamnho da lista onde os dados estão

    if dados_totais == 0:
        return {
            "total_observacoes": 0,
            "resumo_conformidade": {},
            "taxa_conformidade": {},
            "eventos_recentes": []
        }

    tipos = []
    for dado in dados:
        tipos.append(dado["tipo_infracao"])

    contagem_tipos = dict(Counter(tipos))

    distribuicao_percentual = {}
    for ocorrencias, qnt in contagem_tipos.items():
        porcentagem = round((qnt / dados_totais) * 100, 1)
        distribuicao_percentual[ocorrencias] = porcentagem

    return {
        "total_observacoes": dados_totais,
        "resumo_conformidade": contagem_tipos,
        "taxa_conformidade": distribuicao_percentual,
        "eventos_recentes": dados
    }
