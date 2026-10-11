"""Teste B — camada temporal de ocorrências (occurrence.py).

Somente payloads sintéticos: SEM banco, SEM rede, SEM câmera.
Cenários: ausência em 1 frame; ausência persistente; intermitente;
oclusão temporária; recuperação; fechamento/reabertura; duas pessoas
na mesma cena; duas câmeras sem vazamento de estado.
"""
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "event_arch"))
sys.path.insert(0, str(HERE.parent / "vision_integration"))

from event_log import EventLog  # noqa: E402
from occurrence import OccurrenceTracker  # noqa: E402
from pipeline import process_frame  # noqa: E402

P0 = (100.0, 100.0, 300.0, 400.0)
P1 = (500.0, 100.0, 700.0, 400.0)
HELMET_P0 = (150.0, 50.0, 250.0, 120.0)
HELMET_P1 = (550.0, 50.0, 650.0, 120.0)
VEST_P0 = (150.0, 250.0, 250.0, 350.0)
VEST_P1 = (550.0, 250.0, 650.0, 350.0)
STRAY_HELMET = (5000.0, 5000.0, 5100.0, 5100.0)
AREA = {"x1": 0.0, "y1": 0.0, "x2": 800.0, "y2": 600.0}


def _frame(*, helmet=False, stray=False, two_people=False):
    """Frame sintético; padrão: pessoa P0 dentro, sem capacete, com colete."""
    p = {"person": [{"confidence": 0.93, "bounding_box_xyxy": P0}]}
    if two_people:
        p["person"].append({"confidence": 0.91, "bounding_box_xyxy": P1})
    if helmet:
        p["helmet"] = [{"confidence": 0.90, "bounding_box_xyxy": HELMET_P0}]
    if stray:
        # Capacete fora de qualquer região -> indeterminado (oclusão/analogia).
        p["helmet"] = [{"confidence": 0.80, "bounding_box_xyxy": STRAY_HELMET}]
    p["vest"] = [{"confidence": 0.88, "bounding_box_xyxy": VEST_P0}]
    if two_people:
        p["vest"].append({"confidence": 0.87, "bounding_box_xyxy": VEST_P1})
        if helmet:
            p["helmet"].append({"confidence": 0.89, "bounding_box_xyxy": HELMET_P1})
    return p


def _ciclo(log, tr, payload, camera="camera_1"):
    return process_frame(
        payload, log, None, camera_id=camera, risk_area=AREA, occurrence=tr
    )


def _codes(events):
    return [e.event for e in events]


def test_defaults_vem_da_configuracao_e_validacao():
    tr = OccurrenceTracker()
    assert tr.confirm_frames >= 1 and tr.resolve_frames >= 1
    try:
        OccurrenceTracker(confirm_frames=0)
    except ValueError:
        pass
    else:
        raise AssertionError("confirm_frames=0 deveria falhar")
    print("[B0] parâmetros da configuração + validação de entrada")


def test_ausencia_em_um_frame_nao_confirma():
    with tempfile.TemporaryDirectory() as tmp:
        tr = OccurrenceTracker(confirm_frames=3, resolve_frames=2)
        log = EventLog(Path(tmp) / "b1.jsonl")
        n, ev = _ciclo(log, tr, _frame())
        assert n == 0 and ev == []
        assert tr.opened == 0
        assert tr.state_of("camera_1", "helmet") == "clear"
    print("[B1] ausência em 1 único frame: nada emitido (não confirma)")


def test_ausencia_persistente_confirma_uma_vez_sem_repeticao():
    with tempfile.TemporaryDirectory() as tmp:
        tr = OccurrenceTracker(confirm_frames=3, resolve_frames=2)
        log = EventLog(Path(tmp) / "b2.jsonl")
        saidas = [_ciclo(log, tr, _frame())[0] for _ in range(5)]
        assert saidas == [0, 0, 1, 0, 0], saidas
        assert tr.opened == 1 and tr.suppressed >= 2
        registros = log.path.read_text(encoding="utf-8").strip().splitlines()
        assert len(registros) == 1, registros
        assert '"pessoa_sem_capacete"' in registros[0]
    print("[B2] ausência persistente: 1 emissão; frames ativos suprimidos")


def test_deteccoes_intermitentes_com_pausa():
    with tempfile.TemporaryDirectory() as tmp:
        tr = OccurrenceTracker(confirm_frames=3, resolve_frames=2)
        log = EventLog(Path(tmp) / "b3.jsonl")
        seq = [_frame(), _frame(stray=True), _frame(), _frame()]
        saidas = [_ciclo(log, tr, p)[0] for p in seq]
        assert saidas == [0, 0, 0, 1], saidas
        assert tr.inconclusive >= 1 and tr.opened == 1
    print("[B3] intermitente com pausa: confirma no 3º frame ausente")


def test_oclusao_nunca_conta_como_ausencia():
    with tempfile.TemporaryDirectory() as tmp:
        tr = OccurrenceTracker(confirm_frames=3, resolve_frames=2)
        log = EventLog(Path(tmp) / "b4.jsonl")
        # Só frames inconclusivos: NUNCA confirma.
        for _ in range(5):
            assert _ciclo(log, tr, _frame(stray=True))[0] == 0
        assert tr.opened == 0
        # Oclusão entre ausências: pausa, não zera nem confirma sozinha.
        saidas = [
            _ciclo(log, tr, _frame())[0],
            _ciclo(log, tr, _frame(stray=True))[0],
            _ciclo(log, tr, _frame())[0],
            _ciclo(log, tr, _frame())[0],
        ]
        assert saidas == [0, 0, 0, 1], saidas
    print("[B4] oclusão: evidência inconclusiva nunca é ausência")


def test_recupera_conformidade_e_fecha_ocorrencia():
    with tempfile.TemporaryDirectory() as tmp:
        tr = OccurrenceTracker(confirm_frames=2, resolve_frames=2)
        log = EventLog(Path(tmp) / "b5.jsonl")
        assert _ciclo(log, tr, _frame())[0] == 0
        n, ev = _ciclo(log, tr, _frame())
        assert n == 1 and _codes(ev) == ["pessoa_sem_capacete"]
        # Recuperação: 2 frames com capacete -> fecha a ocorrência.
        assert _ciclo(log, tr, _frame(helmet=True))[0] == 0
        n2, ev2 = _ciclo(log, tr, _frame(helmet=True))
        assert n2 == 1 and _codes(ev2) == ["pessoa_com_capacete"]
        assert tr.resolved == 1
        assert tr.state_of("camera_1", "helmet") == "clear"
    print("[B5] recuperação confirmada encerra a ocorrência (com_*)")


def test_fechamento_e_reabertura():
    with tempfile.TemporaryDirectory() as tmp:
        tr = OccurrenceTracker(confirm_frames=1, resolve_frames=1)
        log = EventLog(Path(tmp) / "b6.jsonl")
        codes = []
        for payload in (_frame(), _frame(helmet=True), _frame()):
            _, ev = _ciclo(log, tr, payload)
            codes.extend(_codes(ev))
        assert codes == [
            "pessoa_sem_capacete",
            "pessoa_com_capacete",
            "pessoa_sem_capacete",
        ]
        assert tr.opened == 2 and tr.resolved == 1
    print("[B6] fechamento + reabertura: nova ocorrência após resolução")


def test_duas_pessoas_agregam_sem_rastreamento():
    with tempfile.TemporaryDirectory() as tmp:
        tr = OccurrenceTracker(confirm_frames=2, resolve_frames=2)
        log = EventLog(Path(tmp) / "b7.jsonl")
        payload = _frame(two_people=True)
        # P1 COM capacete, P0 SEM -> regra conservadora: ausência domina.
        payload["helmet"] = [{"confidence": 0.89, "bounding_box_xyxy": HELMET_P1}]
        assert _ciclo(log, tr, payload)[0] == 0
        n, ev = _ciclo(log, tr, payload)
        assert n == 1 and _codes(ev) == ["pessoa_sem_capacete"]
        assert ev[0].metadata["person_ref"] == 0  # fonte ausente (efêmero)
        # Colete presente para ambas -> nenhuma ocorrência de colete.
        assert tr.state_of("camera_1", "vest") == "clear"
        assert tr.opened == 1  # apenas helmet
    print("[B7] duas pessoas: agregação conservadora por (câmera, EPI)")


def test_duas_cameras_sem_compartilhar_estado():
    with tempfile.TemporaryDirectory() as tmp:
        tr = OccurrenceTracker(confirm_frames=2, resolve_frames=2)
        log = EventLog(Path(tmp) / "b8.jsonl")
        assert _ciclo(log, tr, _frame(), camera="camera_1")[0] == 0
        n1, _ = _ciclo(log, tr, _frame(), camera="camera_1")
        assert n1 == 1  # camera_1 confirmou
        # camera_2 começa do zero: 1º frame NÃO herda a confirmação.
        assert _ciclo(log, tr, _frame(), camera="camera_2")[0] == 0
        n2, ev2 = _ciclo(log, tr, _frame(), camera="camera_2")
        assert n2 == 1 and ev2[0].metadata["camera_id"] == "camera_2"
        assert tr.opened == 2
    print("[B8] duas câmeras: estados independentes (chave camera_id+tipo)")


def test_metadata_no_contrato_do_ingest():
    with tempfile.TemporaryDirectory() as tmp:
        tr = OccurrenceTracker(confirm_frames=1, resolve_frames=1)
        log = EventLog(Path(tmp) / "b9.jsonl")
        _, ev = _ciclo(log, tr, _frame())
        esperado = {
            "label", "confidence", "bbox", "camera_id", "person_ref",
            "context", "conf_pessoa", "conf_epi", "bbox_epi",
        }
        assert set(ev[0].metadata.keys()) == esperado
        assert ev[0].metadata["context"] == "inside"
        assert 0.0 <= ev[0].metadata["confidence"] <= 1.0
    print("[B9] metadados no contrato IngestMetadata (campos exatos)")
