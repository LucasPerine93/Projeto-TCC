"""Testes do backend do painel: migração, revisão (status), período e conformidade.

    cd python && python3 -m unittest -v test_painel
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "python")))
import test_pipeline  # noqa: F401  (instala os stubs arduino/fastapi e importa detector antes de banco)
import detector
import banco
import amostragem

PREVIEW_DB = os.environ.get("TCC_PREVIEW_DB", "")   # opcional: banco antigo p/ testar a migração


def inserir(caminho, quando, tipo, status="pendente"):
    con = sqlite3.connect(caminho)
    con.execute("INSERT INTO ocorrencias (timestamp,tipo_infracao,posicao_x,posicao_y,caminho_foto,caixas,status) "
                "VALUES (?,?,?,?,?,?,?)",
                (quando.strftime("%Y-%m-%dT%H:%M:%S"), tipo, 100.0, 200.0, "/x/foto.jpg", None, status))
    con.commit(); con.close()


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "seguranca.db")
        p = mock.patch.multiple(banco, CAMINHO_PENDRIVE=self.tmp.name, CAMINHO_BANCO=self.db,
                                PASTA_FOTOS=os.path.join(self.tmp.name, "ev"))
        p.start(); self.addCleanup(p.stop); self.addCleanup(self.tmp.cleanup)
        amostragem._baldes.clear(); amostragem._ultima_gravacao = 0.0
        self.assertTrue(banco.inicializar_banco(self.db))

    def test_leitura_sem_tabela_nao_quebra(self):
        os.remove(self.db)
        self.assertEqual(banco.dados_ocorrencias(), [])
        r = banco.calcular_dados_dashboard(7)
        self.assertEqual(r["ocorrencias"]["total"], 0); self.assertIsNone(r["conformidade"])

    def test_migracao_de_banco_antigo(self):
        con = sqlite3.connect(self.db)
        con.execute("DROP TABLE ocorrencias")
        con.execute("""CREATE TABLE ocorrencias (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
            tipo_infracao TEXT NOT NULL, posicao_x REAL, posicao_y REAL, conf_pessoa REAL, conf_capacete REAL,
            conf_colete REAL, caminho_foto TEXT)""")
        con.execute("INSERT INTO ocorrencias (timestamp,tipo_infracao,caminho_foto) VALUES ('2026-10-13T08:40:00','Sem colete','/a/b.jpg')")
        con.commit(); con.close()
        linhas = banco.dados_ocorrencias()
        self.assertEqual(len(linhas), 1)
        self.assertEqual((linhas[0]["status"], linhas[0]["motivo"], linhas[0]["caminho_foto"]), ("pendente", None, "b.jpg"))

    def test_revisao_nao_apaga(self):
        inserir(self.db, datetime.now(), "Sem capacete")
        oid = banco.dados_ocorrencias()[0]["id"]
        r = banco.revisar_ocorrencia(oid, "descartada", "  EPI visível mas não detectado ")
        self.assertTrue(r["sucesso"]); self.assertEqual(r["motivo"], "EPI visível mas não detectado")
        linha = banco.dados_ocorrencias()[0]
        self.assertEqual((linha["status"], linha["motivo"]), ("descartada", "EPI visível mas não detectado"))
        self.assertTrue(linha["revisado_em"])
        r = banco.revisar_ocorrencia(oid, "pendente")                       # reabrir
        self.assertIsNone(banco.dados_ocorrencias()[0]["revisado_em"])
        self.assertFalse(banco.revisar_ocorrencia(oid, "qualquer")["sucesso"])
        self.assertFalse(banco.revisar_ocorrencia("abc", "confirmada")["sucesso"])
        self.assertFalse(banco.revisar_ocorrencia(9999, "confirmada")["sucesso"])

    def test_periodo_e_descartadas(self):
        agora = datetime.now()
        inserir(self.db, agora, "Sem capacete")
        inserir(self.db, agora, "Sem colete", status="descartada")          # falso positivo: fora da contagem
        inserir(self.db, agora - timedelta(days=3), "Sem capacete")
        inserir(self.db, agora - timedelta(days=20), "Sem colete")
        hoje = banco.calcular_dados_dashboard(1)
        self.assertEqual(hoje["ocorrencias"], {"total": 1, "pendentes": 1, "confirmadas": 0, "descartadas": 1})
        self.assertEqual(hoje["infracoes_por_tipo"], {"Sem capacete": 1})
        sete = banco.calcular_dados_dashboard(7)
        self.assertEqual(sete["infracoes_por_tipo"], {"Sem capacete": 2})
        self.assertEqual(banco.calcular_dados_dashboard(30)["ocorrencias"]["total"], 3)
        self.assertEqual(sete["periodo"]["ate"], agora.date().isoformat())
        self.assertEqual(sete["periodo"]["dias"], 7)

    def test_conformidade_via_detector(self):
        # 3 pessoas x 20 frames: 1 completa, 1 sem capacete, 1 sem colete
        specs = test_pipeline_specs()
        with mock.patch.object(banco, "pendrive_pronto", return_value=True), \
                mock.patch.object(amostragem, "INTERVALO_GRAVACAO", 0), \
                mock.patch.object(detector.servidor, "box_risco", None), \
                mock.patch.object(detector.servidor, "risco", False), \
                mock.patch.object(banco, "verificar_pendrive", return_value=True):
            test_pipeline.resetar_estado()
            for _ in range(20):
                detector.operario_detectado(specs, None)      # sem foto: nao salva ocorrencia, mas AMOSTRA
        r = banco.calcular_dados_dashboard(1)
        self.assertEqual(r["pessoas_observadas"], 60)
        self.assertEqual(r["trilhas"], 3)
        self.assertEqual(r["conformidade"], 33.3)
        self.assertEqual((r["capacete"], r["colete"]), (66.7, 66.7))
        self.assertIsNone(r["fora_de_risco"])                  # nenhuma area definida
        self.assertEqual(r["ocorrencias"]["total"], 0)         # conformidade vem do denominador, nao das infracoes
        self.assertEqual(len(r["serie_diaria"]), 1)

    def test_chaves_antigas_preservadas(self):
        inserir(self.db, datetime.now(), "Sem capacete")
        r = banco.calcular_dados_dashboard()
        for chave in ("total_observacoes", "resumo_conformidade", "taxa_conformidade", "eventos_recentes"):
            self.assertIn(chave, r)


def test_pipeline_specs():
    pessoas = [test_pipeline.pessoa(x) for x in (50, 250, 450)]
    return {"person": pessoas,
            "helmet": [test_pipeline.capacete(50), test_pipeline.capacete(250)],      # o 3o fica sem capacete
            "vest": [test_pipeline.colete(250), test_pipeline.colete(450)]}           # o 1o fica sem colete


if __name__ == "__main__":
    unittest.main(verbosity=2)
