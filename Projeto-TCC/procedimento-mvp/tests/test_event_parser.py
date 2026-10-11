"""Testes do interpretador de eventos: entrada bruta -> evento padronizado."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "event_arch"))

from event_parser import parse_command, parse_mega

# Respostas do Mega viram eventos padronizados.
assert parse_mega("BASE").event == "base_confirmada"
assert parse_mega("motor_esquerdo").event == "motor_esquerdo_confirmado"
assert parse_mega("MOTOR_DIREITO").event == "motor_direito_confirmado"
assert parse_mega("SUPORTE_BATERIA").event == "suporte_bateria_confirmado"

# Linhas desconhecidas não geram evento.
assert parse_mega("QUALQUER_COISA") is None
assert parse_mega("1 - BASE") is None  # linha do banner do sketch
assert parse_mega("") is None

# Comandos do terminal.
assert parse_command("1") == ("event", parse_mega("BASE"))
assert parse_command("2")[1].event == "motor_esquerdo_confirmado"
assert parse_command("3")[1].event == "motor_direito_confirmado"
assert parse_command("4")[1].event == "suporte_bateria_confirmado"
assert parse_command(" r ") == ("special", None)
assert parse_command("P") == ("special", None)

# Comandos inválidos.
assert parse_command("9") == ("invalid", None)
assert parse_command("xyz") == ("invalid", None)
assert parse_command("") == ("invalid", None)

print("[OK] event_parser: todos os testes passaram.")
