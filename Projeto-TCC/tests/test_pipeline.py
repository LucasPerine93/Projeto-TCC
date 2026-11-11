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
import time
import types
import unittest
from types import SimpleNamespace
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
import amostragem  # noqa: E402
import assistente  # noqa: E402
import servidor  # noqa: E402


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
    servidor._ui_telemetria_ultimo = 0.0
    servidor._telemetria_sequencia = 0
    # Estado dos buffers de trajetoria/exposicao (Etapas 4 e 5)
    detector._TRAJETORIA_BUFFER.clear()
    detector._ULTIMA_AMOSTRA_TRAJETORIA.clear()
    detector._TRILHA_EM_EVENTO.clear()
    detector._ACUMULADO_EXPOSICAO.clear()
    detector._ULTIMA_AMOSTRA_EXPOSICAO = None
    detector._FLUSH_EXPOSICAO = 0.0


class TestTelemetriaGemeo(unittest.TestCase):
    def setUp(self):
        resetar_estado()

    def test_payload_rate_limit_e_frame_vazio(self):
        operario = detector.Operario(
            box_xyxy=(10, 20, 30, 80),
            tem_colete=False,
            tem_capacete=True,
            risco_detectado=True,
            conf_pessoa=0.96,
            conf_capacete=0.91,
            conf_colete=None,
            track_id=7,
        )

        with mock.patch.object(servidor.ui, "send_message") as enviar, \
                mock.patch.object(servidor.time, "time", side_effect=[100.0, 100.1, 100.25]):
            self.assertTrue(servidor.enviar_telemetria([operario]))
            self.assertFalse(servidor.enviar_telemetria([operario]))
            self.assertTrue(servidor.enviar_telemetria([]))

        self.assertEqual(enviar.call_count, 2)
        canal, payload = enviar.call_args_list[0].args
        self.assertEqual(canal, "telemetria_gemeo")
        self.assertEqual(payload, {
            "source": "real",
            "timestamp": 100000,
            "sequence": 1,
            "frame": {"w": 720, "h": 480},
            "workers": [{
                "id": "7",
                "bbox": [10, 20, 30, 80],
                "ppe": {"helmet": True, "vest": False},
                "confidence": {"person": 0.96, "helmet": 0.91, "vest": None},
                "inRisk": True,
            }],
        })
        self.assertEqual(enviar.call_args_list[1].args[1]["workers"], [])
        self.assertEqual(enviar.call_args_list[1].args[1]["sequence"], 2)

    def test_area_de_risco_usa_ponto_dos_pes(self):
        # O centro geométrico está fora, mas a base central toca a área.
        self.assertTrue(detector.verificar_area_risco([40, 300, 80, 360], (20, 100, 100, 320)))
        self.assertFalse(detector.verificar_area_risco([40, 300, 80, 319], (20, 100, 100, 320)))


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


# ---------------------------------------------------------------------------
# Novas verificações (Etapas 3 a 5 do Plano de Evolução)
# ---------------------------------------------------------------------------

class TestProjecaoPlanta(unittest.TestCase):
    """Etapa 3: projeção do ponto dos pés para a planta via homografia."""

    def _calib(self, H, frame=None):
        return {"camId": "1A", "H": H, "frame": frame or {"w": 720, "h": 480}}

    def test_identidade_centro_da_planta(self):
        # pés no centro horizontal e vertical baixo: u=200, v=120 (na H identidade)
        # px=200, py=120 na planta 320x240 -> x_m=5.0, z_m=0.0
        x_m, z_m, idx = detector.projetar_pe_para_planta((0, 0, 400, 120), self._calib([[1, 0, 0], [0, 1, 0], [0, 0, 1]]))
        self.assertAlmostEqual(x_m, 5.0, places=5)
        self.assertAlmostEqual(z_m, 0.0, places=5)
        self.assertEqual(idx, 30 * 80 + 50)  # row 30, col 50

    def test_escala_da_homografia(self):
        H = [[0.8, 0, 0], [0, 0.8, 0], [0, 0, 1]]
        x_m, z_m, idx = detector.projetar_pe_para_planta((0, 0, 400, 120), self._calib(H))
        # px=160, py=96 -> x_m=0.0, z_m=-3.0
        self.assertAlmostEqual(x_m, 0.0, places=5)
        self.assertAlmostEqual(z_m, -3.0, places=5)
        self.assertEqual(idx, 24 * 80 + 40)  # row 24, col 40

    def test_frame_da_calibracao(self):
        # com o frame da calibração em 360x240 o detector é escalado 0.5x antes da H
        H = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        x_m, z_m, idx = detector.projetar_pe_para_planta((0, 0, 200, 60), self._calib(H, frame={"w": 360, "h": 240}))
        self.assertAlmostEqual(x_m, -13.75, places=5)   # px=50 -> (50/320)*40-20 = -13.75
        self.assertAlmostEqual(z_m, -11.25, places=5)  # py=30 -> (30/240)*30-15 = -11.25
        self.assertEqual(idx, 7 * 80 + 12)  # row 7, col 12

    def test_calib_invalida_ou_ausente(self):
        self.assertEqual(detector.projetar_pe_para_planta((0, 0, 400, 120), None), (None, None, None))
        self.assertEqual(detector.projetar_pe_para_planta((0, 0, 400, 120), {"H": [[1, 0, 0]]}), (None, None, None))
        self.assertEqual(detector.projetar_pe_para_planta((0, 0, 400, 120), {"H": "lixo"}), (None, None, None))
        self.assertEqual(detector.projetar_pe_para_planta(None, self._calib([[1, 0, 0], [0, 1, 0], [0, 0, 1]])), (None, None, None))


class TestEspacialBanco(unittest.TestCase):
    """Etapa 3: migração das colunas x_m/z_m/celula_idx e leitura via SELECT."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.multiple(
            banco,
            CAMINHO_PENDRIVE=self.tmp.name,
            CAMINHO_BANCO=os.path.join(self.tmp.name, "banco.db"),
            PASTA_FOTOS=os.path.join(self.tmp.name, "evidencias"),
        )
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        v = mock.patch.object(banco, "verificar_pendrive", return_value=True)
        v.start()
        self.addCleanup(v.stop)

    def test_migracao_adiciona_colunas_e_tabelas(self):
        banco.inicializar_banco(banco.CAMINHO_BANCO)
        con = sqlite3.connect(banco.CAMINHO_BANCO)
        try:
            colunas = {r[1] for r in con.execute("PRAGMA table_info(ocorrencias)")}
            self.assertIn("x_m", colunas)
            self.assertIn("z_m", colunas)
            self.assertIn("celula_idx", colunas)
            tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("trajetoria", tabelas)
            self.assertIn("exposicao_celula", tabelas)
        finally:
            con.close()

    def test_salvar_cena_e_ler_posicao(self):
        registros = [{
            "tipo_infracao": "Sem capacete",
            "posicao_operario": [10, 20, 30, 80],
            "conf_pessoa": 0.9,
            "conf_capacete": None,
            "conf_colete": None,
            "box_capacete": None,
            "box_colete": None,
            "x_m": 5.5,
            "z_m": -2.25,
            "celula_idx": 1234,
        }]
        ids = banco.salvar_cena(b"\xff\xd8jpg\xff\xd9", registros, [])
        self.assertEqual(len(ids), 1)
        ocorrencias = banco.dados_ocorrencias()
        self.assertEqual(len(ocorrencias), 1)
        self.assertAlmostEqual(ocorrencias[0]["x_m"], 5.5)
        self.assertAlmostEqual(ocorrencias[0]["z_m"], -2.25)
        self.assertEqual(ocorrencias[0]["celula_idx"], 1234)


class TestTrajetoriaEMapaCalor(unittest.TestCase):
    """Etapas 4 e 5: trajetória por ocorrência e mapa de calor por célula."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.multiple(
            banco,
            CAMINHO_PENDRIVE=self.tmp.name,
            CAMINHO_BANCO=os.path.join(self.tmp.name, "banco.db"),
            PASTA_FOTOS=os.path.join(self.tmp.name, "evidencias"),
        )
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        v = mock.patch.object(banco, "verificar_pendrive", return_value=True)
        v.start()
        self.addCleanup(v.stop)
        # cria o arquivo de banco para que os helpers não o tratem como ausente
        banco.inicializar_banco(banco.CAMINHO_BANCO)

    def _criar_ocorrencia(self):
        registros = [{
            "tipo_infracao": "Sem capacete",
            "posicao_operario": [10, 20, 30, 80],
            "conf_pessoa": 0.9,
            "conf_capacete": None,
            "conf_colete": None,
            "box_capacete": None,
            "box_colete": None,
            "x_m": 1.0,
            "z_m": 2.0,
            "celula_idx": 10,
        }]
        ids = banco.salvar_cena(b"\xff\xd8jpg\xff\xd9", registros, [])
        self.assertTrue(ids)
        return ids[0]

    def test_salvar_e_ler_trajetoria_via_rota(self):
        id_ocorrencia = self._criar_ocorrencia()
        pontos = [
            {"t_ms": 3000, "x_m": 1.0, "z_m": 2.0, "helmet": 0, "vest": 1, "in_risk": 0, "fonte": "real"},
            {"t_ms": 1000, "x_m": 1.1, "z_m": 2.1, "helmet": 0, "vest": 1, "in_risk": 0, "fonte": "real"},
        ]
        self.assertTrue(banco.salvar_pontos_trajetoria(id_ocorrencia, pontos))

        resposta = servidor._trajetoria_ocorrencia(id_ocorrencia)
        self.assertEqual(resposta["ocorrencia_id"], id_ocorrencia)
        # ordenado por t_ms
        self.assertEqual([p["t_ms"] for p in resposta["pontos"]], [1000, 3000])
        self.assertEqual(resposta["pontos"][0]["x_m"], 1.1)
        self.assertEqual(resposta["pontos"][0]["helmet"], False)

    def test_trajetoria_rota_id_invalido(self):
        resposta = servidor._trajetoria_ocorrencia("abc")
        # handlers expõe (dict, status) no estilo WebUI do app
        self.assertEqual(resposta[1], 400)
        self.assertIn("erro", resposta[0])

    def test_mapa_calor_via_rota(self):
        ok = banco.registrar_exposicao_celulas({42: (10.0, 2.0, 1)})
        self.assertTrue(ok)
        ok = banco.registrar_exposicao_celulas({42: (10.0, 6.0, 2)})
        self.assertTrue(ok)

        resposta = servidor._mapa_calor()
        celulas = resposta["celulas"]
        self.assertEqual(len(celulas), 1)
        self.assertEqual(celulas[0]["celula_idx"], 42)
        self.assertAlmostEqual(celulas[0]["segundos_presenca"], 20.0)
        self.assertAlmostEqual(celulas[0]["segundos_infracao"], 8.0)
        self.assertEqual(celulas[0]["total_eventos"], 3)
        self.assertAlmostEqual(celulas[0]["taxa_infracao"], 0.4)

    def test_mapa_calor_sem_banco(self):
        # sem arquivo de banco: mapa vazio, sem exceção
        self.assertEqual(banco.obter_mapa_calor(), [])

    def test_limpar_trajetoria_antiga(self):
        id_ocorrencia = self._criar_ocorrencia()
        banco.salvar_pontos_trajetoria(id_ocorrencia, [
            {"t_ms": 1000, "x_m": 0.0, "z_m": 0.0, "helmet": 0, "vest": 0, "in_risk": 0},
        ])
        self.assertEqual(len(banco.obter_trajetoria(id_ocorrencia)), 1)
        # ocorrência recente não é apagada
        self.assertEqual(banco.limpar_trajetoria_antiga(90), 0)
        self.assertEqual(len(banco.obter_trajetoria(id_ocorrencia)), 1)


class TestTelemetriaComPosicao(unittest.TestCase):
    """Etapa 3: o payload de telemetria carrega a posição na planta quando projetada."""

    def setUp(self):
        resetar_estado()

    def test_payload_com_posicao_na_planta(self):
        operario = detector.Operario(
            box_xyxy=(10, 20, 30, 80),
            tem_colete=True,
            tem_capacete=True,
            risco_detectado=False,
            conf_pessoa=0.96,
            conf_capacete=0.91,
            conf_colete=0.88,
            track_id=9,
            pos_x_m=5.5,
            pos_z_m=-2.25,
            celula_idx=1234,
        )
        with mock.patch.object(servidor.ui, "send_message") as enviar, \
                mock.patch.object(servidor.time, "time", side_effect=[100.0]):
            self.assertTrue(servidor.enviar_telemetria([operario]))

        canal, payload = enviar.call_args_list[0].args
        self.assertEqual(canal, "telemetria_gemeo")
        self.assertEqual(payload["workers"][0]["position"], {"x": 5.5, "z": -2.25})


class TestAtribuicaoGlobalTrilhas(unittest.TestCase):
    """Etapa 6: atribuicao global gulosa por placar (nao pela ordem da lista)."""

    def setUp(self):
        resetar_estado()

    def test_par_melhor_vence_ordem_da_lista(self):
        # trilha ja existe na posicao exata do segundo operario
        alvo = detector.Operario(box_xyxy=(0, 50, 200, 350))
        detector.associar_trilhas([alvo], 1000.0)
        id_alvo = alvo.track_id

        # no frame seguinte o vizinho vem ANTES na lista: a escolha gulosa por
        # ordem de iteracao entregaria a trilha a ele; a global entrega ao par
        # de maior placar (o operario na posicao exata).
        vizinho = detector.Operario(box_xyxy=(30, 50, 230, 350))
        exato = detector.Operario(box_xyxy=(0, 50, 200, 350))
        detector.associar_trilhas([vizinho, exato], 1010.0)

        self.assertEqual(exato.track_id, id_alvo)
        self.assertNotEqual(vizinho.track_id, id_alvo)

    def test_trilha_e_operario_usados_no_maximo_uma_vez(self):
        # duas trilhas ativas e dois operarios: cada um fica com uma trilha
        a = detector.Operario(box_xyxy=(0, 50, 100, 350))
        detector.associar_trilhas([a], 1000.0)
        b = detector.Operario(box_xyxy=(250, 50, 350, 350))
        detector.associar_trilhas([b], 1002.0)
        self.assertEqual(len({a.track_id, b.track_id}), 2)

        a2 = detector.Operario(box_xyxy=(5, 50, 105, 350))
        b2 = detector.Operario(box_xyxy=(255, 50, 355, 350))
        detector.associar_trilhas([a2, b2], 1010.0)

        self.assertEqual(a2.track_id, a.track_id)
        self.assertEqual(b2.track_id, b.track_id)

    def test_ambiguidade_entre_duas_trilhas_abre_nova(self):
        a = detector.Operario(box_xyxy=(0, 50, 100, 350))
        detector.associar_trilhas([a], 1000.0)
        b = detector.Operario(box_xyxy=(250, 50, 350, 350))
        detector.associar_trilhas([b], 1002.0)  # longe da trilha A -> trilha nova

        # operario equidistant das duas trilhas: placares empatados (< MARGEM)
        # e a regra antiga de ambiguidade deve criar uma trilha nova.
        q = detector.Operario(box_xyxy=(125, 50, 225, 350))
        detector.associar_trilhas([q], 1004.0)

        self.assertEqual(len({a.track_id, b.track_id, q.track_id}), 3)


class TestAssistenteSomenteLeitura(unittest.TestCase):
    """Etapa 8: POST /assistente com dados reais; consulta APENAS leitura."""

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
        banco.inicializar_banco(banco.CAMINHO_BANCO)

        # amostragem guarda baldes em memoria: isola o teste do resto da suite
        amostragem._baldes.clear()
        amostragem._ultima_gravacao = 0.0
        self.addCleanup(amostragem._baldes.clear)

        try:
            import seguranca
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except Exception:
            self.skipTest("FastAPI/httpx reais indisponiveis neste ambiente")

        self.seguranca = seguranca
        seguranca._sessoes.clear()
        seguranca._sessoes["tok-teste"] = time.time() + seguranca.DURACAO_SESSAO
        self.addCleanup(seguranca._sessoes.clear)

        app = FastAPI()

        @app.post("/assistente")
        async def _rota(req: seguranca.Request):
            return await servidor._assistente(req)

        self.client = TestClient(app)

    def _post(self, pergunta, sessao=True):
        return self.client.post(
            "/assistente",
            json={"pergunta": pergunta},
            cookies={"sessao": "tok-teste"} if sessao else {},
            headers={"X-Requested-With": "painel"},
        )

    def _semear_ocorrencias(self):
        frame = b"\xff\xd8fake-jpeg\xff\xd9"
        # [0] com capacete e sem colete -> "Sem colete"; [1] com colete e sem
        # capacete -> "Sem capacete" (duas trilhas distintas, sem cooldown)
        specs = {
            "person": [pessoa(50), pessoa(250)],
            "helmet": [capacete(50)],
            "vest": [colete(250)],
        }
        with mock.patch.object(detector.servidor, "box_risco", None), \
                mock.patch.object(detector.servidor, "risco", False):
            detector.operario_detectado(specs, frame)

    def test_pergunta_requer_sessao(self):
        resposta = self._post("resumo", sessao=False)
        self.assertEqual(resposta.status_code, 401)

    def test_pergunta_vazia_retorna_400(self):
        # o handler segue o estilo do servidor: devolve (dict, status)
        class _Req:
            def __init__(self):
                self.cookies = {"sessao": "tok-teste"}
                self.headers = {"x-requested-with": "painel"}

            async def json(self):
                return {"pergunta": "  "}

        import asyncio
        resposta = asyncio.run(servidor._assistente(_Req()))
        self.assertEqual(resposta[1], 400)
        self.assertIn("erro", resposta[0])

    def test_ocorrencias_tipos_e_revisao(self):
        self._semear_ocorrencias()
        resposta = self._post("Quais foram as ocorrencias mais frequentes nesta semana?")
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.json()
        texto = corpo["resposta"]
        self.assertIn("2 ocorr", texto)          # 1 sem capacete + 1 sem colete
        self.assertIn("Sem capacete", texto)
        self.assertIn("Sem colete", texto)
        self.assertIn("pendente", texto)         # status de revisao
        self.assertIsNone(corpo["acao"])         # ocorrencias nao fogem para o 3D

    def test_conformidade_mostra_meta_e_periodo_anterior(self):
        agora = time.time()
        conformes = [SimpleNamespace(tem_capacete=True, tem_colete=True, risco_detectado=False)
                     for _ in range(4)]
        amostragem.registrar(conformes, area_ativa=False, agora=agora)
        amostragem.descarregar(banco.CAMINHO_BANCO, forcar=True, agora=agora)
        # semana anterior: metade conformes, para aparecer a comparacao
        metade = [SimpleNamespace(tem_capacete=(i % 2 == 0), tem_colete=True, risco_detectado=False)
                  for i in range(4)]
        amostragem.registrar(metade, area_ativa=False, agora=agora - 8 * 24 * 3600)
        amostragem.descarregar(banco.CAMINHO_BANCO, forcar=True, agora=agora - 8 * 24 * 3600)

        resposta = self._post("Compare o periodo atual com o anterior.")
        self.assertEqual(resposta.status_code, 200)
        texto = resposta.json()["resposta"]
        self.assertIn("100", texto)
        self.assertIn("meta de 95", texto)      # meta de conformidade
        self.assertIn("anterior", texto)

    def test_zona_critica_gera_acao_para_o_gemeo(self):
        banco.registrar_exposicao_celulas({1234: (100.0, 50.0, 5)})
        resposta = self._post("Qual zona apresentou mais eventos?")
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.json()
        self.assertIn("1234", corpo["resposta"])
        acao = corpo["acao"]
        self.assertIsNotNone(acao)
        self.assertEqual(acao["tipo"], "focar_gemeo")
        x_esperado, z_esperado = assistente.idx_para_coords(1234)
        self.assertAlmostEqual(acao["x_m"], round(x_esperado, 1), places=1)
        self.assertAlmostEqual(acao["z_m"], round(z_esperado, 1), places=1)

    def test_resumo_geral(self):
        self._semear_ocorrencias()
        resposta = self._post("Me de um panorama geral do canteiro.")
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.json()
        self.assertIn("Resumo", corpo["resposta"])
        self.assertIn("ocorrência", corpo["resposta"])

    def test_pergunta_vazia_no_motor(self):
        resultado = assistente.responder("")
        self.assertIn("resposta", resultado)
        self.assertEqual(resultado["acao"], None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
