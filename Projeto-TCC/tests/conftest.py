"""Bootstrap dos testes: garante ``python/`` no ``sys.path`` e a ordem de
importacao ``detector`` antes de ``banco`` (evita o import circular
banco <-> servidor, igual ao main.py). Tambem instala stubs de
``arduino.*`` e ``fastapi`` quando as libs reais nao existem (Windows/CI).
"""
import os
import sys
import types

PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "python"))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


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
import detector  # noqa: E402,F401
import banco  # noqa: E402,F401
