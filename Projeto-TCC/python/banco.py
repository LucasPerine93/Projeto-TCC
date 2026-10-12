from fastapi.responses import FileResponse
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
        print("[SUCESSO]: Pendrive montado e pronto")
        return True
    else:
        print("[ERRO]: Pendrive não encontrado")
        return False


def inicializar_banco(caminho_banco: str) -> bool:

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
                caminho_foto TEXT
            )
        """)
        conexao.commit()
        print("[BANCO]: Tabela de ocorrências pronta!")
        return True
    
    except sqlite3.Error as e:
        print(f"[ERRO]: Falha no banco de dados | detalhes do erro: {e}")
        return False
    
    finally:
        if conexao:
            conexao.close()

def salvar_ocorrencias(tipo_infracao, posicao_operario, conf_pessoa, conf_capacete, conf_colete, frame):
    if verificar_pendrive(CAMINHO_PENDRIVE) and inicializar_banco(CAMINHO_BANCO):
        nome_imagem = f"foto_{int(time.time())}_{tipo_infracao}_{posicao_operario}.jpg"
        caminho_salvar = os.path.join(PASTA_FOTOS, nome_imagem)
        os.makedirs(PASTA_FOTOS, exist_ok=True)

        with open(caminho_salvar, "wb") as arquivo:
            arquivo.write(frame)

        try:
            conexao = sqlite3.connect(CAMINHO_BANCO)
            cursor = conexao.cursor()
    
            sql = """
                INSERT INTO ocorrencias (timestamp, tipo_infracao, posicao_x, posicao_y, conf_pessoa, conf_capacete, conf_colete, caminho_foto)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
    
            px, py = (posicao_operario[0] + posicao_operario[2]) / 2, (posicao_operario[1] + posicao_operario[3]) / 2
            cursor.execute(sql, (time.strftime("%Y-%m-%dT%H:%M:%S"), tipo_infracao, px, py, conf_pessoa, conf_capacete, conf_colete, caminho_salvar))
    
            conexao.commit()
            
        except sqlite3.Error as e:
            print(f"[ERRO]: Falha no banco de dados | detalhes do erro: {e}")

        finally:
            if conexao:
                conexao.close()

        print("[SUCESSO]: Imagem salva!")

def listar_fotos():
    # Verifica se a pasta existe
    if os.path.exists(PASTA_FOTOS):
        # Pega os arquivos dentro da pasta
        return sorted(os.listdir(PASTA_FOTOS), reverse=True) # Envia a lista de fotos da mais recente para a mais antiga
    return []

def pegar_foto(nome_foto: str):
    caminho_foto = os.path.join(PASTA_FOTOS, os.path.basename(nome_foto))
    if os.path.exists(caminho_foto):
        return FileResponse(caminho_foto, media_type="image/jpeg") # Envia a foto
        
    return "Foto não encontrada"