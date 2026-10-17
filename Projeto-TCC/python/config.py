"""Parametros centrais do TCC (fonte unica da verdade no backend).

Este modulo NAO importa detector/banco/amostragem/seguranca/servidor:
ficar sem dependencias evita qualquer import circular. Os demais modulos
importam daqui (``import config``) e mantem aliases com os nomes antigos
para compatibilidade com testes (mock.patch) e com o preview_server.
"""
import os

# ---------------------------------------------------------------------------
# Caminhos de producao (Arduino UNO Q / Docker: tudo sob /app)
# ---------------------------------------------------------------------------
CAMINHO_PENDRIVE = "/app/pendrive"
CAMINHO_BANCO = os.path.join(CAMINHO_PENDRIVE, "seguranca.db")
PASTA_FOTOS = os.path.join(CAMINHO_PENDRIVE, "evidencias")

# ---------------------------------------------------------------------------
# Detector / YOLO + camera
# ---------------------------------------------------------------------------
CAMERA_SOURCE = 0
CAMERA_RESOLUTION = (720, 480)
CAMERA_FPS = 10
DETECCAO_CONFIANCA = 0.5
DETECCAO_DEBOUNCE_SEC = 0

# Faixa vertical do corpo (fracao da altura da caixa da pessoa, a partir do
# topo) onde cada EPI deve ter o seu centro.
ZONA_CAPACETE = (-0.15, 0.35)
ZONA_COLETE = (0.36, 0.80)

# Cooldown do log de seguranca (s) e cooldown POR trilha e POR tipo (s).
TEMPO_ESPERA = 5
TEMPO_ESPERA_SALVAR = 20
# A trilha vive pelo menos tanto quanto o cooldown: se a pessoa some atras
# de um obstaculo e volta antes do cooldown acabar, mantem o track_id.
TEMPO_VIDA_TRILHA = float(TEMPO_ESPERA_SALVAR)

# Rastreamento geometrico entre frames.
LIMIAR_IOU = 0.15          # IoU minimo para considerar a mesma trajetoria
LIMIAR_DISTANCIA = 0.6     # fracao da menor diagonal entre as duas caixas
MARGEM_AMBIGUIDADE = 0.05  # diferenca minima de placar para descartar empate

# ---------------------------------------------------------------------------
# Banco (SQLite)
# ---------------------------------------------------------------------------
COLUNAS_NOVAS = {
    "caixas": "TEXT",
    # Revisao pelo tecnico (nada e apagado: descartar = falso positivo).
    "status": "TEXT NOT NULL DEFAULT 'pendente'",
    "motivo": "TEXT",
    "revisado_em": "TEXT",
}
STATUS_VALIDOS = ("pendente", "confirmada", "descartada")

# ---------------------------------------------------------------------------
# Amostragem (denominador pessoa-frame da taxa de conformidade)
# ---------------------------------------------------------------------------
INTERVALO_GRAVACAO = 30
MAX_BALDES_EM_MEMORIA = 120  # se o pendrive sumir, guarda ~2 h e descarta o mais antigo
CAMPOS_AMOSTRA = ("pessoas", "com_capacete", "com_colete", "conformes",
                  "risco_ativo", "em_risco", "trilhas_novas")

# ---------------------------------------------------------------------------
# Painel (fonte da verdade Python/docs; o JS em tela_painel.js e espelho)
# ---------------------------------------------------------------------------
META_CONFORMIDADE = 95
LIMITE_CRITICO_CONFORMIDADE = 85

# ---------------------------------------------------------------------------
# Seguranca (senha SEMPRE via variavel de ambiente, nunca hardcoded)
# ---------------------------------------------------------------------------
VAR_SENHA_HASH = "TCC_SENHA_HASH"
COOKIE_SESSAO = "sessao"
DURACAO_SESSAO = 8 * 3600
DURACAO_TICKET = 30
MAX_FALHAS = 5
BLOQUEIO_BASE = 30
ITERACOES_PBKDF2 = 200_000
