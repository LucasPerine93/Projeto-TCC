"""
Módulo de amostragem baseada em Pessoa-Frame para cálculo científico de conformidade.

Denominador da taxa de conformidade: quantas pessoas foram OBSERVADAS, não só quantas erraram.

Unidade = "pessoa-frame" (uma pessoa vista em um frame). A razão conformes/pessoas
independe do FPS e elimina falsos positivos de frames vazios. As contagens ficam
em memória e são gravadas em baldes de 1 minuto a cada INTERVALO_GRAVACAO s
(poupa o pendrive: 10 fps nunca vira 10 escritas por segundo).

Métrica Científica:
- pessoas_observadas: total de detecções válidas (denominador)
- conformes: pessoas com capacete E colete E fora de área de risco
- taxa = conformes / pessoas_observadas × 100
"""
import sqlite3
import time

INTERVALO_GRAVACAO = 30
MAX_BALDES_EM_MEMORIA = 120          # se o pendrive sumir, guarda ~2 h e descarta o mais antigo

_baldes = {}                         # "YYYY-MM-DDTHH:MM" -> dict de contadores
_ultima_gravacao = 0.0

CAMPOS = ("pessoas", "com_capacete", "com_colete", "conformes",
          "risco_ativo", "em_risco", "trilhas_novas")


def criar_tabela(con):
    """Cria tabela amostras_minuto com 7 contadores agregados por minuto (chave primária)."""
    con.execute("""CREATE TABLE IF NOT EXISTS amostras_minuto (
        minuto TEXT PRIMARY KEY,
        pessoas INTEGER NOT NULL DEFAULT 0, com_capacete INTEGER NOT NULL DEFAULT 0,
        com_colete INTEGER NOT NULL DEFAULT 0, conformes INTEGER NOT NULL DEFAULT 0,
        risco_ativo INTEGER NOT NULL DEFAULT 0, em_risco INTEGER NOT NULL DEFAULT 0,
        trilhas_novas INTEGER NOT NULL DEFAULT 0)""")


def registrar(operarios, area_ativa, trilhas_novas=0, agora=None):
    """
    Incrementa contadores do minuto atual baseado nas detecções do frame.
    
    Chamar uma vez por frame, DEPOIS de associar_trilhas e definir tem_*/risco_detectado.
    Baldes acumulam em memória até descarregar() gravá-los no SQLite.
    """
    agora = agora or time.time()
    chave = time.strftime("%Y-%m-%dT%H:%M", time.localtime(agora))
    b = _baldes.setdefault(chave, dict.fromkeys(CAMPOS, 0))
    for o in operarios:
        b["pessoas"] += 1
        b["com_capacete"] += bool(o.tem_capacete)
        b["com_colete"] += bool(o.tem_colete)
        b["conformes"] += bool(o.tem_capacete and o.tem_colete and not o.risco_detectado)
        if area_ativa:
            b["risco_ativo"] += 1
            b["em_risco"] += bool(o.risco_detectado)
    b["trilhas_novas"] += trilhas_novas
    while len(_baldes) > MAX_BALDES_EM_MEMORIA:
        _baldes.pop(min(_baldes))


def descarregar(caminho_banco, forcar=False, agora=None):
    """
    Grava baldes pendentes no SQLite somando valores existentes (INSERT...ON CONFLICT).
    
    Args:
        caminho_banco: Path do seguranca.db
        forcar: Ignora INTERVALO_GRAVACAO e grava imediatamente
        agora: Timestamp customizado (default: time.time())
    
    Returns:
        True se gravou com sucesso, False se pulou ou falhou (mantém baldes em memória)
    """
    global _ultima_gravacao
    agora = agora or time.time()
    if not _baldes or (not forcar and agora - _ultima_gravacao < INTERVALO_GRAVACAO):
        return False
    con = None
    try:
        con = sqlite3.connect(caminho_banco)
        criar_tabela(con)
        for minuto, b in list(_baldes.items()):
            con.execute(
                "INSERT INTO amostras_minuto (minuto, %s) VALUES (?, %s) ON CONFLICT(minuto) DO UPDATE SET %s"
                % (", ".join(CAMPOS), ", ".join("?" * len(CAMPOS)), ", ".join(f"{c}={c}+excluded.{c}" for c in CAMPOS)),
                (minuto, *[b[c] for c in CAMPOS]))
        con.commit()
        _baldes.clear()
        _ultima_gravacao = agora
        return True
    except sqlite3.Error:
        return False           # mantém na memória e tenta de novo na próxima janela
    finally:
        if con:
            con.close()


def _taxa(parte, total):
    """Calcula porcentagem arredondada com 1 casa decimal. Retorna None se total=0."""
    return None if not total else round(100 * parte / total, 1)


def resumo(caminho_banco, desde_iso, ate_iso):
    """
    Calcula taxas agregadas do período [desde_iso, ate_iso) e série diária.
    
    Args:
        caminho_banco: Path do seguranca.db
        desde_iso: Data/hora início (formato "YYYY-MM-DDTHH:MM")
        ate_iso: Data/hora fim exclusivo
    
    Returns:
        Dict com pessoas_observadas, conformidade%, capacete%, colete%,
        fora_de_risco%, trilhas, serie_diaria. None = sem dados (nunca 0% inventado)
    """
    con = sqlite3.connect(caminho_banco)
    try:
        criar_tabela(con)
        t = dict(zip(CAMPOS, con.execute(
            "SELECT %s FROM amostras_minuto WHERE minuto >= ? AND minuto < ?"
            % ", ".join(f"COALESCE(SUM({c}),0)" for c in CAMPOS), (desde_iso, ate_iso)).fetchone()))
        diario = [{"dia": d, "conformidade": _taxa(c, p), "pessoas": p} for d, p, c in con.execute(
            "SELECT substr(minuto,1,10), SUM(pessoas), SUM(conformes) FROM amostras_minuto "
            "WHERE minuto >= ? AND minuto < ? GROUP BY 1 ORDER BY 1", (desde_iso, ate_iso))]
    finally:
        con.close()
    return {
        "pessoas_observadas": t["pessoas"], "trilhas": t["trilhas_novas"],
        "conformidade": _taxa(t["conformes"], t["pessoas"]),
        "capacete": _taxa(t["com_capacete"], t["pessoas"]),
        "colete": _taxa(t["com_colete"], t["pessoas"]),
        "fora_de_risco": None if not t["risco_ativo"] else round(100 - 100 * t["em_risco"] / t["risco_ativo"], 1),
        "serie_diaria": diario,
    }
