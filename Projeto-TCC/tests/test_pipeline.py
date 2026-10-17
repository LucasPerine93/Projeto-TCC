"""Testes do pipeline de EPIs: _to_float, associação EPI<->operário, rastreio,
callback seguro e ponta a ponta (organizar_dado -> analisar_seguranca ->
filtrar_salvamento -> salvar_cena -> SQLite + .jpg).

Rodar (sem pytest, sem hardware):

    python -m unittest discover -s tests -v   (a partir de Projeto-TCC/)

Fora da placa, as libs ``arduino.*`` e ``fastapi`` são substituídas por stubs.
Na placa (libs reais instaladas) os stubs não entram.
"""
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "python")))

import numpy as np


def _instalar_stubs():
    def mod(nome, **attrs):
        m = types.ModuleType(nome)
        m.__dict__.update(attrs)
        sys.modules[nome] = m

    class _Det:
        def __init__(self, **_):
            pass

        def on_detect_all(self, _f):
            pass

    class _Cam:
        def __init__(self, **_):
            pass

    class _UI:
        def on_message(self, *a, **k):
            pass

        def send_message(self, *a, **k):
            pass

        def expose_api(self, *a, **k):
            pass

    try:
        import arduino.app_bricks.video_objectdetection  # noqa: F401
    except ImportError:
        mod("arduino")
        mod("arduino.app_bricks")
        mod("arduino.app_peripherals")
        mod("arduino.app_bricks.video_objectdetection", VideoObjectDetection=_Det)
        mod("arduino.app_peripherals.camera", Camera=_Cam)
        mod("arduino.app_bricks.web_ui", WebUI=_UI)
    try:
        import fastapi.responses  # noqa: F401
    except ImportError:
        mod("fastapi")
        mod("fastapi.responses", FileResponse=object)


_instalar_stubs()

# detector primeiro: banco <-> servidor tem import circular (igual ao main.py)
import detector  # noqa: E402
import banco  # noqa: E402


def pessoa(x, y1=50, y2=350, largura=100, conf=0.9):
    return {
        "bounding_box_xyxy": np.array([x, y1, x + largura, y2], dtype=np.float32),
        "confidence": np.float32(conf),
    }


def capacete(x, conf=0.8):
    return {"bounding_box_xyxy": [x + 30, 50, x + 70, 90], "confidence": conf}


def colete(x, conf=0.7):
    return {"bounding_box_xyxy": [x + 20, 140, x + 80, 260], "confidence": conf}


def resetar_estado():
    detector._trilhas_ativas.clear()
    detector._ultima_ocorrencia.clear()
    detector._proximo_track_id = 1
    detector.ultimo_alerta = 0.0


class TestToFloat(unittest.TestCase):
    def test_tipos(self):
        for f in (detector._to_float, banco._to_float):
            self.assertEqual(f(None), 0.0)
            self.assertIsNone(f(None, None))
            self.assertEqual(f(3), 3.0)
            self.assertEqual(f(2.5), 2.5)
            self.assertEqual(f(True), 1.0)
            self.assertEqual(f(" 7,5 "), 7.5)
            self.assertEqual(f("abc", -1.0), -1.0)
            self.assertEqual(f(""), 0.0)
            self.assertEqual(f(np.float32(0.5)), 0.5)
            self.assertEqual(f(np.int64(4)), 4.0)
            self.assertEqual(f(np.array(1.5)), 1.5)      # 0-d
            self.assertEqual(f(np.array([2.0])), 2.0)    # 1 elemento
            self.assertEqual(f(np.array([1.0, 2.0]), -1.0), -1.0)
            self.assertEqual(f([1, 2], -1.0), -1.0)
            self.assertEqual(f(float("nan"), -1.0), -1.0)
            self.assertEqual(f(float("inf"), -1.0), -1.0)
            self.assertIs(type(f(np.float32(0.5))), float)

    def test_get_conf_ausente_e_0(self):
        self.assertEqual(detector._get_conf({}), 0.0)
        self.assertEqual(detector._get_conf({"confidence": None}), 0.0)
        self.assertEqual(detector._get_conf({"score": "x"}), 0.0)
        self.assertAlmostEqual(detector._get_conf({"score": np.float32(0.25)}), 0.25)


class TestAtribuirEpi(unittest.TestCase):
    def setUp(self):
        resetar_estado()

    def _rodar(self, pessoas, helmets, vests):
        specs = {"person": pessoas, "helmet": helmets, "vest": vests}
        with mock.patch.object(detector, "filtrar_salvamento"), \
                mock.patch.object(detector, "analisar_seguranca"):
            return detector.organizar_dado(specs, None, False, None)

    def test_tres_operarios_completos(self):
        xs = (50, 250, 450)
        r = self._rodar([pessoa(x) for x in xs], [capacete(x) for x in xs], [colete(x) for x in xs])
        self.assertEqual([(o.tem_capacete, o.tem_colete) for o in r], [(True, True)] * 3)
        # confianca vem da deteccao do EPI (antes ficava sempre 0.5)
        self.assertEqual([o.conf_capacete for o in r], [0.8] * 3)
        self.assertEqual([o.conf_colete for o in r], [0.7] * 3)
        self.assertEqual(r[1].box_capacete, [280.0, 50.0, 320.0, 90.0])

    def test_so_um_capacete_para_tres_pessoas(self):
        xs = (50, 250, 450)
        r = self._rodar([pessoa(x) for x in xs], [capacete(250)], [])
        self.assertEqual([o.tem_capacete for o in r], [False, True, False])

    def test_epi_nunca_vai_para_duas_pessoas(self):
        # duas pessoas lado a lado; um unico capacete na area das duas
        a, b = pessoa(100, largura=200), pessoa(150, largura=200)
        capa = {"bounding_box_xyxy": [200, 50, 240, 90], "confidence": 0.9}
        r = self._rodar([a, b], [capa], [])
        self.assertEqual(sum(o.tem_capacete for o in r), 1)

    def test_epi_invalido_ignorado(self):
        r = self._rodar([pessoa(50)], [{"bounding_box_xyxy": None}, "lixo", capacete(50)], [])
        self.assertTrue(r[0].tem_capacete)


class TestTrilha(unittest.TestCase):
    def setUp(self):
        resetar_estado()

    def test_tempo_vida_igual_cooldown(self):
        self.assertEqual(detector.TEMPO_VIDA_TRILHA, float(detector.TEMPO_ESPERA_SALVAR))

    def test_oclusao_curta_mantem_id(self):
        o1 = detector.Operario(box_xyxy=(100, 50, 200, 350))
        detector.associar_trilhas([o1], 1000.0)
        o2 = detector.Operario(box_xyxy=(102, 50, 202, 350))
        detector.associar_trilhas([o2], 1015.0)  # sumiu 15 s (> 5 s antigos)
        self.assertEqual(o1.track_id, o2.track_id)
        o3 = detector.Operario(box_xyxy=(102, 50, 202, 350))
        detector.associar_trilhas([o3], 1015.0 + 21)  # passou do limite
        self.assertNotEqual(o3.track_id, o1.track_id)


class TestPontaAPonta(unittest.TestCase):
    def setUp(self):
        resetar_estado()
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.multiple(
            banco,
            CAMINHO_PENDRIVE=self.tmp.name,
            CAMINHO_BANCO=os.path.join(self.tmp.name, "seguranca.db"),
            PASTA_FOTOS=os.path.join(self.tmp.name, "evidencias"),
        )
        p.start()
        self.addCleanup(p.stop)
        v = mock.patch.object(banco, "verificar_pendrive", return_value=True)
        v.start()
        self.addCleanup(v.stop)
        self.addCleanup(self.tmp.cleanup)

    def _linhas(self):
        con = sqlite3.connect(banco.CAMINHO_BANCO)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute("SELECT * FROM ocorrencias ORDER BY id")]
        finally:
            con.close()

    def _specs(self):
        # 3 operarios: [0] sem capacete, [1] completo, [2] sem colete
        return {
            "person": [pessoa(50), pessoa(250), pessoa(450)],
            "helmet": [capacete(250), capacete(450)],
            "vest": [colete(50), colete(250)],
        }

    def test_fluxo_completo(self):
        frame = b"\xff\xd8fake-jpeg\xff\xd9"
        with mock.patch.object(detector.servidor, "box_risco", None), \
                mock.patch.object(detector.servidor, "risco", False):
            ops = detector.operario_detectado(self._specs(), frame)

        self.assertEqual([(o.tem_capacete, o.tem_colete) for o in ops],
                         [(False, True), (True, True), (True, False)])

        linhas = self._linhas()
        self.assertEqual(len(linhas), 2)  # o completo nao gera ocorrencia
        self.assertEqual({l["tipo_infracao"] for l in linhas}, {"Sem capacete", "Sem colete"})

        # UMA foto para a cena inteira
        fotos = os.listdir(banco.PASTA_FOTOS)
        self.assertEqual(len(fotos), 1)
        self.assertEqual({os.path.basename(l["caminho_foto"]) for l in linhas}, set(fotos))
        # nome com milissegundos: foto_<13 digitos>_...
        self.assertRegex(fotos[0], r"^foto_\d{13}_")
        with open(os.path.join(banco.PASTA_FOTOS, fotos[0]), "rb") as f:
            self.assertEqual(f.read(), frame)

        sem_capacete = next(l for l in linhas if l["tipo_infracao"] == "Sem capacete")
        self.assertIsNone(sem_capacete["conf_capacete"])           # NULL, nao 0.0
        self.assertAlmostEqual(sem_capacete["conf_pessoa"], 0.9, places=5)
        self.assertAlmostEqual(sem_capacete["conf_colete"], 0.7, places=5)
        caixas = json.loads(sem_capacete["caixas"])
        self.assertEqual(caixas["pessoa"], [50, 50, 150, 350])
        self.assertIsNone(caixas["capacete"])
        self.assertEqual(caixas["colete"], [70, 140, 130, 260])
        self.assertTrue(caixas["cena_id"].startswith("cena_"))
        self.assertEqual(len(caixas["operarios"]), 3)              # cena completa
        self.assertEqual(len({l["id"] for l in linhas}), 2)

        # repetir o mesmo frame dentro do cooldown nao duplica
        with mock.patch.object(detector.servidor, "box_risco", None), \
                mock.patch.object(detector.servidor, "risco", False):
            detector.operario_detectado(self._specs(), frame)
        self.assertEqual(len(self._linhas()), 2)

        # descartar uma ocorrencia preserva a foto; a ultima remove
        r = banco.excluir_ocorrencia(linhas[0]["id"])
        self.assertTrue(r["sucesso"])
        self.assertFalse(r["foto_excluida"])
        self.assertEqual(len(os.listdir(banco.PASTA_FOTOS)), 1)
        r = banco.excluir_ocorrencia(linhas[1]["id"])
        self.assertTrue(r["foto_excluida"])
        self.assertEqual(os.listdir(banco.PASTA_FOTOS), [])

    def test_area_de_risco_gera_ocorrencia(self):
        specs = {"person": [pessoa(50)], "helmet": [capacete(50)], "vest": [colete(50)]}
        with mock.patch.object(detector.servidor, "box_risco", [0, 0, 300, 400]), \
                mock.patch.object(detector.servidor, "risco", True):
            detector.operario_detectado(specs, b"jpg")
        self.assertEqual([l["tipo_infracao"] for l in self._linhas()], ["Invasao de area de risco"])

    def test_callback_nunca_levanta(self):
        with mock.patch.object(banco, "salvar_cena", side_effect=RuntimeError("disco cheio")), \
                mock.patch.object(detector.servidor, "box_risco", None), \
                mock.patch.object(detector.servidor, "risco", False):
            ops = detector.operario_detectado(self._specs(), b"jpg")  # nao levanta
        self.assertEqual(len(ops), 3)  # o erro foi isolado na etapa de salvamento
        with mock.patch.object(detector, "organizar_dado", side_effect=ValueError("boom")):
            self.assertEqual(detector.operario_detectado({}, None), [])

    def test_falha_no_log_nao_impede_salvamento(self):
        with mock.patch.object(detector, "analisar_seguranca", side_effect=RuntimeError("log")), \
                mock.patch.object(detector.servidor, "box_risco", None), \
                mock.patch.object(detector.servidor, "risco", False):
            detector.operario_detectado(self._specs(), b"jpg")
        self.assertEqual(len(self._linhas()), 2)

    def test_sem_pessoas_e_sem_frame(self):
        self.assertEqual(detector.operario_detectado({"person": []}, b"jpg"), [])
        with mock.patch.object(detector.servidor, "box_risco", None), \
                mock.patch.object(detector.servidor, "risco", False):
            detector.operario_detectado(self._specs(), None)  # lib antiga: sem foto
        self.assertFalse(os.path.exists(banco.PASTA_FOTOS))


if __name__ == "__main__":
    unittest.main(verbosity=2)
