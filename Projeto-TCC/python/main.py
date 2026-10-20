"""
Ponto de entrada do backend do Painel de EPIs.

Inicializa módulos e inicia loop principal do Arduino App:
- detector.py: YOLO11n + tracking de operários
- servidor.py: FastAPI + WebSocket para WebUI
- banco.py: SQLite para ocorrências e amostras pessoa-frame
- App.run(): executa detecção em tempo real com callback detector.analisar_seguranca()
"""
from arduino.app_utils import App
import detector
import servidor
import banco

App.run()