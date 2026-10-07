"""Interpreta entradas brutas e as converte em eventos padronizados.

As entradas podem vir de qualquer origem:
  - Arduino Mega 2560 (serial USB)
  - terminal / teclado
  - futuramente, visão computacional (ex.: CAPACETE com confiança)

A máquina de estados só enxerga o evento padronizado, nunca a origem.
Assim, Arduino e visão computacional alimentam a mesma máquina de estados.
"""

from dataclasses import dataclass, replace
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class ParsedEvent:
    """Evento padronizado gerado a partir de uma entrada bruta."""
    raw: str     # valor bruto recebido (ex.: "BASE", "1")
    event: str   # nome do evento para a máquina de estados (ex.: "base_confirmada")
    label: str   # nome legível (ex.: "Base")
    metadata: Optional[Dict] = None  # opcional: dados extras (ex.: detecção da visão)


# Respostas enviadas pelo Arduino Mega 2560 quando um comando é recebido.
MEGA_EVENTS: Dict[str, ParsedEvent] = {
    "BASE": ParsedEvent("BASE", "base_confirmada", "Base"),
    "MOTOR_ESQUERDO": ParsedEvent("MOTOR_ESQUERDO", "motor_esquerdo_confirmado", "Motor esquerdo"),
    "MOTOR_DIREITO": ParsedEvent("MOTOR_DIREITO", "motor_direito_confirmado", "Motor direito"),
    "SUPORTE_BATERIA": ParsedEvent("SUPORTE_BATERIA", "suporte_bateria_confirmado", "Suporte da bateria"),
}

# Comandos digitados no terminal Python que geram evento de procedimento.
COMMANDS: Dict[str, ParsedEvent] = {
    "1": MEGA_EVENTS["BASE"],
    "2": MEGA_EVENTS["MOTOR_ESQUERDO"],
    "3": MEGA_EVENTS["MOTOR_DIREITO"],
    "4": MEGA_EVENTS["SUPORTE_BATERIA"],
}

# Comandos especiais (não geram evento de procedimento).
# R = RESET, P = PING. Ambos são encaminhados ao Mega.
SPECIAL_COMMANDS = {"R", "P"}

# Respostas de controle do Mega que não são eventos do procedimento.
CONTROL_RESPONSES = {"PING", "PONG", "READY"}


def parse_mega(raw: str) -> Optional[ParsedEvent]:
    """Converte uma linha enviada pelo Mega em evento padronizado."""
    return MEGA_EVENTS.get((raw or "").strip().upper())


def parse_command(raw: str) -> Tuple[str, Optional[ParsedEvent]]:
    """Classifica um comando digitado no terminal.

    Retorna (tipo, evento) onde tipo é:
      "event"   -> comando de detecção (1, 2, 3, 4)
      "special" -> comando especial (R, P)
      "invalid" -> comando não reconhecido
    """
    cmd = (raw or "").strip().upper()
    if cmd in COMMANDS:
        return "event", COMMANDS[cmd]
    if cmd in SPECIAL_COMMANDS:
        return "special", None
    return "invalid", None


# --- Detecções da visão computacional ---------------------------------------

# Limiar de confiança PROVISÓRIO (apenas valor padrão para testes).
# É configurável por parâmetro em parse_detection(); não representa a taxa
# de acuracidade do modelo (questão de treinamento) e será definido em
# configuração em etapa futura.
DEFAULT_CONFIDENCE_THRESHOLD = 0.5

# Classes detectadas -> eventos padronizados.
# Para apoiar uma nova classe futura, basta adicionar uma linha aqui.
# PERSON/HELMET/VEST: labels do modelo de visão (on_detect_all). O gate de
# confidence (threshold=0.5) é aplicado aqui; os eventos de detecção ficam
# INTERNOS à camada de visão — só conformidades chegam ao log observacional.
DETECTION_EVENTS: Dict[str, ParsedEvent] = {
    "CAPACETE": ParsedEvent("CAPACETE", "capacete_detectado", "Capacete"),
    "LUVA": ParsedEvent("LUVA", "luva_detectada", "Luva"),
    "PERSON": ParsedEvent("PERSON", "pessoa_detectada", "Pessoa"),
    "HELMET": ParsedEvent("HELMET", "capacete_detectado", "Capacete"),
    "VEST": ParsedEvent("VEST", "colete_detectado", "Colete"),
}


def parse_detection(
    payload,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> Tuple[str, Optional[ParsedEvent]]:
    """Converte uma detecção da visão computacional em evento padronizado.

    Entrada (dict), ex.:
        {"label": "CAPACETE", "confidence": 0.91,
         "timestamp": "...", "bbox": [x1, y1, x2, y2], "camera_id": "camera_1"}

    Os campos extras (timestamp, confidence, bbox, camera_id) são
    preservados em ParsedEvent.metadata e seguem até o EventLog.

    Regra de confiança: confidence >= threshold -> aceita (>= inclui o limite).

    Retorna (tipo, evento) onde tipo é:
      "accepted"       -> detecção convertida em evento padronizado
      "low_confidence" -> confiança abaixo do threshold (rejeitada)
      "unknown_class"  -> classe não mapeada (rejeitada)
      "invalid"        -> payload com dados ausentes/inválidos

    Ordem de avaliação: validade dos dados -> classe mapeada -> confiança.
    """
    if not isinstance(payload, dict):
        return "invalid", None

    label = payload.get("label")
    if not isinstance(label, str) or not label.strip():
        return "invalid", None

    confidence = payload.get("confidence")
    if type(confidence) not in (int, float):  # bool é excluído de propósito
        return "invalid", None
    if not 0.0 <= confidence <= 1.0:
        return "invalid", None

    parsed = DETECTION_EVENTS.get(label.strip().upper())
    if parsed is None:
        return "unknown_class", None

    if confidence < threshold:
        return "low_confidence", None

    metadata = {
        chave: payload[chave]
        for chave in ("timestamp", "confidence", "bbox", "camera_id")
        if chave in payload
    }
    return "accepted", replace(parsed, metadata=metadata)
