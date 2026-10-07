from arduino.app_bricks.video_objectdetection import VideoObjectDetection
from arduino.app_peripherals.camera import Camera
import servidor
import math

helmet = False
vest = False

contador_frames = 0

posicao_anterior = None
limite_movimento = 45

camera = Camera(source=0, resolution=(720, 480), fps=10)
deteccao = VideoObjectDetection(camera=camera, debounce_sec=2, confidence=0.5, camera_preview=True)

def verificar_EPIs(specs_frame, frame=None):
    global helmet, vest, posicao_anterior, contador_frames
    
    if frame is None:
        return

    x1, y1, x2, y2 = specs_frame.get('bounding_box_xyxy')
    centro_atual = ((x1 + x2) / 2, (y1 + y2) / 2)

    risco = servidor.risco

    if risco == 1:
        ar_centro = servidor.centro
        ar_widht = servidor.width
        ar_height = servidor.height

        dist1 = math.dist(centro_atual, ar_centro)

        w = float(ar_widht)
        h = float(ar_height)
            
        if dist1 < abs(w) and dist1 < abs(h):
            contador_frames += 1
            if contador_frames >= 2:
                print("[ALERTA]: Operario presente em area de risco")
                contador_frames = 0

    if posicao_anterior is not None:
        distancia = math.dist(centro_atual, posicao_anterior)
        if distancia < limite_movimento:
            return

    if helmet is False:
        print("[LOG]: Capacete não detectado")

    if vest is False:
        print("[LOG]: Colete não detectado")

    if (vest is True) and (helmet is True):
        print("[LOG]: Tudo seguro, EPIs detectados")

    helmet = False
    vest = False

    posicao_anterior = centro_atual


def helmet_detectado(*args):
    global helmet
    helmet = True
    
def vest_detectado(*args):
    global vest
    vest = True

deteccao.on_detect('person', verificar_EPIs)
deteccao.on_detect('helmet', helmet_detectado)
deteccao.on_detect('vest', vest_detectado)

# --- INICIO: integracao vision_integration (plano v3.4.2) --------------------
# Conecta o payload REAL do on_detect_all ao pipeline observacional do projeto
# Victor (vision_integration). NAO altera os callbacks on_detect acima
# (alertas legados continuam independentes) e nao duplica o adapter.
#
# Localizacao portavel do pacote vision_integration (sem caminhos absolutos fixos):
#   1) variavel de ambiente TCC_MVP_ROOT (raiz do projeto que contem vision_integration/)
#   2) busca relativa na arvore de diretorios a partir deste arquivo
import os
import sys
from pathlib import Path


def _raiz_vision_integration():
    """Retorna a raiz que contem vision_integration/pipeline.py, ou None."""
    variavel = os.environ.get("TCC_MVP_ROOT")
    if variavel:
        candidato = Path(variavel)
        if (candidato / "vision_integration" / "pipeline.py").is_file():
            return candidato
    aqui = Path(__file__).resolve().parent
    for _ in range(6):
        if (aqui / "vision_integration" / "pipeline.py").is_file():
            return aqui
        if aqui.is_dir():
            for filho in sorted(aqui.iterdir()):
                if filho.is_dir() and (filho / "vision_integration" / "pipeline.py").is_file():
                    return filho
        aqui = aqui.parent
    return None


RAIZ_MVP = _raiz_vision_integration()

if RAIZ_MVP is None:
    print("[VISION] vision_integration NAO encontrado "
          "(defina TCC_MVP_ROOT). Integracao observacional DESATIVADA.")
else:
    sys.path.insert(0, str(RAIZ_MVP))
    from vision_integration.pipeline import process_frame
    from event_debounce import EventDebounce
    from event_log import EventLog

    # EventLog existente do projeto Victor -> data/procedure_events.jsonl
    log_observacional = EventLog(RAIZ_MVP / "data" / "procedure_events.jsonl")
    # Debounce observacional proprio (chave evento/camera_id/person_ref).
    debounce_observacional = EventDebounce()

    def _risk_area_atual():
        """servidor.py (centro/width/height/risco) -> formato de context.py.

        risco ausente/0 ou area ainda nao marcada -> None (contexto no_area).
        Converte centro+dimensoes de volta para retangulo x1,y1,x2,y2
        (width/height do servidor sao negativos: x1-x2 / y1-y2).
        """
        if not servidor.risco:
            return None
        if servidor.centro is None or servidor.width is None or servidor.height is None:
            return None
        cx, cy = servidor.centro
        metade_w = abs(float(servidor.width)) / 2.0
        metade_h = abs(float(servidor.height)) / 2.0
        return {
            "x1": cx - metade_w,
            "y1": cy - metade_h,
            "x2": cx + metade_w,
            "y2": cy + metade_h,
        }

    def _ao_detectar_tudo(detections, frame=None):
        # frame (JPEG) NAO e utilizado: o pipeline trabalha so com deteccoes.
        # camera_id vem da configuracao da integracao (pipeline/config.py).
        total = 0
        if isinstance(detections, dict):
            total = sum(len(v) for v in detections.values() if isinstance(v, list))
        n, _ = process_frame(
            detections,
            log=log_observacional,
            debounce=debounce_observacional,
            risk_area=_risk_area_atual(),
        )
        print(f"[VISION] on_detect_all recebido | deteccoes={total} | conformidades={n}")

    _on_detect_all = getattr(deteccao, "on_detect_all", None)
    if callable(_on_detect_all):
        _on_detect_all(_ao_detectar_tudo)
        print("[VISION] on_detect_all registrado -> vision_integration.process_frame")
    else:
        print("[VISION] on_detect_all INDISPONIVEL nesta versao da biblioteca.")
# --- FIM: integracao vision_integration ---------------------------------------

