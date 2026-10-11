"""Testes do parse_detection: detecção simulada da visão -> evento padronizado.

Somente payloads falsos — nenhum modelo ou câmera é utilizado aqui.
"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "event_arch"))

from event_parser import DEFAULT_CONFIDENCE_THRESHOLD, parse_detection

# 1) Detecção válida (payload completo, com campos extras ignorados)
tipo, evento = parse_detection({
    "label": "CAPACETE",
    "confidence": 0.91,
    "timestamp": "2026-10-03T12:00:00Z",
    "bbox": [10, 20, 60, 80],
    "camera_id": "camera_1",
})
assert tipo == "accepted", tipo
assert evento.event == "capacete_detectado"
assert evento.label == "Capacete"
assert evento.raw == "CAPACETE"

# payload mínimo também é aceito
tipo, evento = parse_detection({"label": "CAPACETE", "confidence": 0.91})
assert tipo == "accepted" and evento.event == "capacete_detectado"

# 2) Confiança abaixo do limite -> rejeitada
tipo, evento = parse_detection({"label": "CAPACETE", "confidence": 0.40})
assert tipo == "low_confidence" and evento is None

# O threshold é configurável por chamada
tipo, _ = parse_detection({"label": "CAPACETE", "confidence": 0.55}, threshold=0.6)
assert tipo == "low_confidence"
tipo, _ = parse_detection({"label": "CAPACETE", "confidence": 0.55}, threshold=0.5)
assert tipo == "accepted"

# Limiar exato é aceito (regra: confidence >= threshold)
tipo, _ = parse_detection({"label": "CAPACETE", "confidence": DEFAULT_CONFIDENCE_THRESHOLD})
assert tipo == "accepted"

# 3) Classe desconhecida -> rejeitada / não mapeada
tipo, evento = parse_detection({"label": "OBJETO_DESCONHECIDO", "confidence": 0.95})
assert tipo == "unknown_class" and evento is None

# 4) Dados inválidos -> sempre "invalid", de forma consistente
casos_invalidos = [
    {},                                          # sem label e sem confidence
    {"confidence": 0.9},                         # label ausente
    {"label": "CAPACETE"},                       # confidence ausente
    {"label": "   ", "confidence": 0.9},         # label vazia
    {"label": "CAPACETE", "confidence": 1.5},    # confiança > 1
    {"label": "CAPACETE", "confidence": -0.1},   # confiança < 0
    {"label": "CAPACETE", "confidence": "0.9"},  # confiança não numérica
    {"label": 123, "confidence": 0.9},           # label não é texto
    {"label": "CAPACETE", "confidence": True},   # bool não é confiança
    "CAPACETE",                                  # payload não é dict
]
for payload in casos_invalidos:
    tipo, evento = parse_detection(payload)
    assert tipo == "invalid" and evento is None, repr(payload)

# 5) Extensibilidade: segunda classe já mapeada
tipo, evento = parse_detection({"label": "LUVA", "confidence": 0.88})
assert tipo == "accepted" and evento.event == "luva_detectada"

# 6) Normalização do label (espaços e minúsculas)
tipo, evento = parse_detection({"label": "  capacete ", "confidence": 0.8})
assert tipo == "accepted" and evento.event == "capacete_detectado"

# Demonstração do fluxo conceitual: detecção -> evento padronizado
demo = parse_detection({"label": "CAPACETE", "confidence": 0.91})[1]
print(f"[DEMO] CAPACETE (0.91) -> {demo.event}")
print("[OK] parse_detection: todos os testes passaram.")
