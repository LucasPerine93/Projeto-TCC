# Painel de EPIs — Detecção de Capacete, Colete e Área de Risco (Arduino UNO Q)

## Visão geral

Sistema embarcado de segurança do trabalho: detecta **pessoas, capacetes,
coletes e invasão de área de risco** com YOLO no **Arduino UNO Q**, grava
evidências (foto + SQLite) no pendrive e expõe um **painel web** (Ao vivo,
Ocorrências, Painel de conformidade) servido pela própria placa.

A **taxa de conformidade** usa denominador real **pessoa-frame** (quantas
pessoas foram *observadas*, não só quantas erraram), com meta de **95 %**.

## Arquitetura de hardware

- **Arduino UNO Q** (compute +/app lab): câmera, YOLO (`VideoObjectDetection`,
  modelo `ei-model-1127250-2`), WebUI + APIs.
- **Pendrive** montado em `/app/pendrive`: `seguranca.db` (SQLite) + `evidencias/*.jpg`.
- **Navegador** (obra/escritório): painel responsivo, tema claro/escuro, PWA.

## Estrutura de pastas

```
Projeto-TCC/
  app.yaml            # definição do App Lab (NÃO mover)
  python/             # backend embarcado
    config.py         # parâmetros centrais (fonte única da verdade)
    detector.py       # pipeline YOLO → trilhas → salvamento
    banco.py          # SQLite, dashboard, revisão
    amostragem.py     # denominador pessoa-frame
    seguranca.py      # login PBKDF2 + cookie HttpOnly
    servidor.py       # WebUI + rotas HTTP
    main.py           # entrypoint (ordem: detector, servidor, banco)
  assets/             # frontend (index.html, css/, js/ SVG puro, libs/)
  tests/              # suíte unittest (conftest garante detector 1º)
  docs/               # arquitetura.md, metodologia.md, api.md

```

## Como configurar a senha

A senha **nunca** fica no código — só o hash PBKDF2 na env `TCC_SENHA_HASH`:

```bash
python python/seguranca.py "minha senha longa"
# exporta o hash impresso:
export TCC_SENHA_HASH='pbkdf2$200000$...$...'
```

## Como rodar os testes

```bash
cd Projeto-TCC
python -m unittest discover -s tests -v
```

Ordem de importação (`detector` antes de `banco`) e stubs `arduino.*`/
`fastapi` são tratados em `tests/conftest.py` — no Windows/CI os testes rodam
sem hardware.

## Documentação

- [Arquitetura e fluxo](docs/arquitetura.md)
- [Metodologia da conformidade](docs/metodologia.md)
- [API HTTP e segurança](docs/api.md)
