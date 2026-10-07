"""Camada de integração observacional da visão computacional (plano v3.4.2).

Separação rígida:
  - ESTE PACOTE gera eventos de conformidade e escreve no EventLog com
    status="observation". NÃO importa state_machine, event_ingest nem
    vision_bridge.
  - O fluxo procedural (event_arch/vision_bridge) continua inalterado.

Ponto de entrada: vision_integration.pipeline.process_frame.
"""
