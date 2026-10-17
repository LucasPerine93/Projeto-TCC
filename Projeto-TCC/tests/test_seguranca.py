"""Testes para seguranca.py – login, sessão, bloqueio por tentativas."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "python")))

# Gera o hash antes de importar seguranca para que a var de ambiente já exista
import seguranca as _bootstrap_hash
_HASH = _bootstrap_hash.gerar_hash("minha_senha_teste")
os.environ["TCC_SENHA_HASH"] = _HASH

from fastapi import FastAPI
from fastapi.testclient import TestClient
import seguranca

# ---------- App mínima para testes ----------
app = FastAPI()

@app.post("/api/login")
async def rota_login(request: seguranca.Request):
    return await seguranca.login(request)

@app.get("/api/sessao")
async def rota_sessao(request: seguranca.Request):
    return seguranca.sessao(request)

@app.post("/api/logout")
async def rota_logout(request: seguranca.Request):
    return seguranca.logout(request)

@app.get("/protegido")
async def rota_protegida(request: seguranca.Request):
    negado = seguranca.exigir(request)
    if negado:
        return negado
    return {"dados": "ok"}

client = TestClient(app)


class TestRotaBloqueada(unittest.TestCase):
    """Rota protegida sem cookie deve retornar 401."""

    def setUp(self):
        seguranca._sessoes.clear()
        seguranca._falhas.clear()

    def test_sem_cookie_retorna_401(self):
        # Client novo para garantir que não há cookies residuais
        c = TestClient(app, cookies={})
        r = c.get("/protegido")
        self.assertEqual(r.status_code, 401)
        self.assertFalse(r.json()["sucesso"])


class TestLoginCorreto(unittest.TestCase):
    """Login com senha certa gera cookie HttpOnly."""

    def setUp(self):
        seguranca._sessoes.clear()
        seguranca._falhas.clear()

    def test_login_gera_cookie(self):
        r = client.post("/api/login", json={"senha": "minha_senha_teste"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["sucesso"])
        # Verifica cookie de sessão
        cookie_header = r.headers.get("set-cookie", "")
        self.assertIn("sessao=", cookie_header)
        self.assertIn("httponly", cookie_header.lower())

    def test_acesso_protegido_apos_login(self):
        r = client.post("/api/login", json={"senha": "minha_senha_teste"})
        self.assertEqual(r.status_code, 200)
        # TestClient mantém cookies automaticamente
        r2 = client.get("/protegido")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["dados"], "ok")


class TestBloqueioTentativas(unittest.TestCase):
    """Após MAX_FALHAS tentativas erradas, retorna 429."""

    def setUp(self):
        seguranca._sessoes.clear()
        seguranca._falhas.clear()

    def test_bloqueio_apos_tentativas(self):
        for i in range(seguranca.MAX_FALHAS):
            r = client.post("/api/login", json={"senha": "errada"})
            self.assertEqual(r.status_code, 401, f"Tentativa {i+1} deveria ser 401")

        # Próxima tentativa deve ser bloqueada (429)
        r = client.post("/api/login", json={"senha": "errada"})
        self.assertEqual(r.status_code, 429)
        self.assertIn("Aguarde", r.json()["mensagem"])


class TestSenhaIncorreta(unittest.TestCase):
    """Login com senha errada retorna 401."""

    def setUp(self):
        seguranca._sessoes.clear()
        seguranca._falhas.clear()

    def test_senha_errada_401(self):
        r = client.post("/api/login", json={"senha": "completamente_errada"})
        self.assertEqual(r.status_code, 401)
        self.assertFalse(r.json()["sucesso"])


if __name__ == "__main__":
    unittest.main()
