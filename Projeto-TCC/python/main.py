"""main.py — Ponto de entrada do aplicativo no Arduino App Lab.

Papel do arquivo
----------------
Inicializa e sobe o app na placa UNO Q: registra as rotas do servidor
(importar ``servidor``), abre/prepara o banco (``banco``) e integra o
detector YOLO de EPIs (``detector``) ao ciclo de vida do ``App`` do App Lab
(``App.run()``, que roda o loop de câmera + WebUI + tarefas agendadas).

Entradas / Saídas
-----------------
- Entradas: câmera configurada no App Lab e requisições HTTP/WebSocket do
  painel (servidas por ``servidor.py``).
- Saídas: servidor WebUI no ar (rotas) e detecções fluindo para
  ``detector.organizar_dado`` durante o loop.

Índice de seções
----------------
1. Importações e ordem de carga (import circular ``servidor`` <-> ``banco``)
2. Inicialização do App Lab

Ordem de importação importa: ``servidor`` e ``banco`` importam um ao outro
(igual ao ciclo original do projeto); ``detector`` deve ser importado antes
de qualquer uso efetivo das classes na partida.
"""
from arduino.app_utils import App
import detector
import servidor
import banco

# ===== 1. Importações concluídas — App Lab pronto para inicializar =====

# ===== 2. Inicialização do App Lab (loop de câmera + WebUI + tarefas) =====
App.run()
