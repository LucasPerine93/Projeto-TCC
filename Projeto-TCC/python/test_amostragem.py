"""Testes para amostragem.py – registrar/resumo e taxas de conformidade."""
import os
import sqlite3
import tempfile
import time
import unittest
from types import SimpleNamespace

# Garante que importamos do diretório correto
import sys
sys.path.insert(0, os.path.dirname(__file__))

import amostragem


def _operario(capacete=True, colete=True, risco=False):
    return SimpleNamespace(tem_capacete=capacete, tem_colete=colete, risco_detectado=risco)


class TestRegistrarEResumo(unittest.TestCase):
    """Ciclo completo: registrar → descarregar → resumo."""

    def setUp(self):
        amostragem._baldes.clear()
        amostragem._ultima_gravacao = 0.0
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db = self._tmp.name

    def tearDown(self):
        os.unlink(self.db)

    def test_conformidade_100(self):
        """Todos com EPI completo e sem risco → 100 %."""
        agora = time.mktime(time.strptime("2026-06-01T10:00", "%Y-%m-%dT%H:%M"))
        ops = [_operario() for _ in range(4)]
        amostragem.registrar(ops, area_ativa=True, agora=agora)
        amostragem.descarregar(self.db, forcar=True, agora=agora)
        r = amostragem.resumo(self.db, "2026-06-01", "2026-06-02")
        self.assertEqual(r["conformidade"], 100.0)
        self.assertEqual(r["pessoas_observadas"], 4)
        self.assertEqual(r["capacete"], 100.0)
        self.assertEqual(r["colete"], 100.0)

    def test_conformidade_parcial(self):
        """2 conformes e 2 não conformes → 50 %."""
        agora = time.mktime(time.strptime("2026-06-01T10:00", "%Y-%m-%dT%H:%M"))
        ops = [
            _operario(capacete=True, colete=True, risco=False),
            _operario(capacete=True, colete=True, risco=False),
            _operario(capacete=False, colete=True, risco=False),   # sem capacete
            _operario(capacete=True, colete=False, risco=False),   # sem colete
        ]
        amostragem.registrar(ops, area_ativa=False, agora=agora)
        amostragem.descarregar(self.db, forcar=True, agora=agora)
        r = amostragem.resumo(self.db, "2026-06-01", "2026-06-02")
        self.assertEqual(r["conformidade"], 50.0)
        self.assertEqual(r["capacete"], 75.0)
        self.assertEqual(r["colete"], 75.0)

    def test_risco_detectado_nao_conforme(self):
        """Operário com EPI completo mas em risco não é conforme."""
        agora = time.mktime(time.strptime("2026-06-01T10:00", "%Y-%m-%dT%H:%M"))
        ops = [
            _operario(capacete=True, colete=True, risco=True),
        ]
        amostragem.registrar(ops, area_ativa=True, agora=agora)
        amostragem.descarregar(self.db, forcar=True, agora=agora)
        r = amostragem.resumo(self.db, "2026-06-01", "2026-06-02")
        self.assertEqual(r["conformidade"], 0.0)
        self.assertEqual(r["fora_de_risco"], 0.0)

    def test_serie_diaria(self):
        """Resumo retorna série diária com dias corretos."""
        for dia in ("01", "02"):
            agora = time.mktime(time.strptime(f"2026-06-{dia}T10:00", "%Y-%m-%dT%H:%M"))
            amostragem.registrar([_operario()], area_ativa=False, agora=agora)
        amostragem.descarregar(self.db, forcar=True)
        r = amostragem.resumo(self.db, "2026-06-01", "2026-06-03")
        self.assertEqual(len(r["serie_diaria"]), 2)
        self.assertEqual(r["serie_diaria"][0]["dia"], "2026-06-01")

    def test_sem_dados_retorna_none(self):
        """Sem registros, conformidade é None."""
        r = amostragem.resumo(self.db, "2099-01-01", "2099-01-02")
        self.assertIsNone(r["conformidade"])
        self.assertEqual(r["pessoas_observadas"], 0)


if __name__ == "__main__":
    unittest.main()
