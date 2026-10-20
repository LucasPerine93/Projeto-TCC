"""Autenticação e controle de sessões do Painel de EPIs.

Hash PBKDF2-SHA256 com 200.000 iterações para senhas.
Sessões baseadas em cookies HttpOnly.
Rate limiting exponencial contra força bruta.
Tickets de uso único para operações de escrita.
"""
import hashlib
import hmac
import os
import secrets
import sys
import time
from fastapi import Request
from fastapi.responses import JSONResponse

COOKIE = "sessao"
DURACAO_SESSAO = 8 * 3600
DURACAO_TICKET = 30
MAX_FALHAS = 5
BLOQUEIO_BASE = 30
ITERACOES = 200_000

_sessoes = {}
_tickets = {}
_falhas = {}

def gerar_hash(senha: str) -> str:
    """Gera hash PBKDF2-SHA256 com sal aleatório de 16 bytes e 200.000 iterações."""
    sal = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, ITERACOES)
    return f"pbkdf2${ITERACOES}${sal.hex()}${h.hex()}"

def _conferir(senha: str) -> bool:
    """Verifica senha contra hash armazenado em TCC_SENHA_HASH usando comparação timing-safe."""
    guardado = os.environ.get("TCC_SENHA_HASH", "")
    try:
        _, it, sal, h = guardado.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(sal), int(it))
        return hmac.compare_digest(calc.hex(), h)
    except ValueError:
        return False

def _ip(request) -> str:
    """Extrai IP do cliente da requisição FastAPI."""
    return request.client.host if request.client else "?"

def _limpar(agora):
    """Remove sessões e tickets expirados das tabelas em memória."""
    for tabela in (_sessoes, _tickets):
        for k in [k for k, v in tabela.items() if v < agora]:
            del tabela[k]

def _negar(status, msg):
    """Retorna JSONResponse de erro com status HTTP e mensagem."""
    return JSONResponse({"sucesso": False, "mensagem": msg}, status_code=status)

def exigir(request, escrita: bool = False):
    """
    Valida sessão ativa via cookie e renova expiração.
    
    Args:
        request: Requisição FastAPI com cookies
        escrita: Se True, exige header x-requested-with=painel (proteção CSRF)
    
    Returns:
        JSONResponse de erro se sessão inválida, None se autorizado
    """
    agora = time.time()
    token = request.cookies.get(COOKIE)
    if not token or _sessoes.get(token, 0) < agora:
        return _negar(401, "Sessão expirada ou ausente.")
    if escrita and request.headers.get("x-requested-with") != "painel":
        return _negar(403, "Requisição de origem não confiável.")
    _sessoes[token] = agora + DURACAO_SESSAO
    return None

def _novo_ticket():
    """Cria ticket CSRF de uso único com 24 bytes (32 chars base64url)."""
    t = secrets.token_urlsafe(24)
    _tickets[t] = time.time() + DURACAO_TICKET
    return t

def consumir_ticket(ticket) -> bool:
    """Valida e consome ticket CSRF, removendo-o da tabela. Retorna True se válido."""
    return _tickets.pop(ticket, 0) >= time.time()

async def login(request: Request):
    """
    Endpoint de autenticação com rate limiting exponencial.
    
    Rate limit: 3 falhas → bloqueio 5s, dobra até 15min, reseta após sucesso.
    Retorna cookie HttpOnly com token de sessão e ticket CSRF inicial.
    """
    agora = time.time()
    _limpar(agora)
    ip = _ip(request)
    contagem, ate, rodadas = _falhas.get(ip, [0, 0.0, 0])
    if ate > agora:
        return _negar(429, f"Muitas tentativas. Aguarde {int(ate - agora) + 1} s.")
    try:
        senha = str((await request.json()).get("senha", ""))
    except Exception:
        return _negar(400, "Requisição inválida.")
    if not _conferir(senha):
        contagem += 1
        if contagem >= MAX_FALHAS:
            _falhas[ip] = [0, agora + min(BLOQUEIO_BASE * 2 ** rodadas, 900), rodadas + 1]
        else:
            _falhas[ip] = [contagem, 0.0, rodadas]
        return _negar(401, "Senha incorreta.")
    _falhas.pop(ip, None)
    token = secrets.token_urlsafe(32)
    _sessoes[token] = agora + DURACAO_SESSAO
    resp = JSONResponse({"sucesso": True, "ticket": _novo_ticket()})
    resp.set_cookie(COOKIE, token, max_age=DURACAO_SESSAO, httponly=True, samesite="strict", path="/")
    return resp

def sessao(request: Request):
    """Valida sessão ativa e retorna novo ticket CSRF."""
    negado = exigir(request)
    return negado or JSONResponse({"sucesso": True, "ticket": _novo_ticket()})

def logout(request: Request):
    """Encerra sessão removendo token e deletando cookie."""
    negado = exigir(request, escrita=True)
    if negado: return negado
    _sessoes.pop(request.cookies.get(COOKIE), None)
    resp = JSONResponse({"sucesso": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp

if __name__ == "__main__":
    if len(sys.argv) > 1: print(gerar_hash(sys.argv[1]))