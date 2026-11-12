# Mapa do Código — Projeto TCC: Painel de EPIs com Gêmeo 3D

## 1. Árvore de Diretórios Comentada

```
Projeto-TCC/
├── python/                          # Back-end: detector, servidor web, persistência
│   ├── main.py                      # Inicialização do App Lab, loop da câmera, integração com o detector
│   ├── detector.py                  # Pipeline de detecção: EPIs, área de risco, projeção, trilhas, buffer circular
│   ├── servidor.py                  # Rotas REST (FastAPI), WebUI (socket.io), telemetria 5 Hz, snapshot, calibração
│   ├── banco.py                     # SQLite: schema, migração, ocorrências, trajetórias, mapa de calor, dashboard
│   ├── amostragem.py                # Métrica Pessoa-Frame: contagem em memória, gravação em baldes de 1 min, taxas
│   ├── seguranca.py                 # Login PBKDF2, sessões por cookie, tickets, rate-limit, CSRF
│   ├── assistente.py                # Assistente IA somente-leitura: intenções, respostas, proxy LLM opcional
│   └── config.py                    # Configurações globais (caminhos, colunas, status, durações)
│
├── assets/                          # Front-end: HTML, CSS, JS
│   ├── index.html                   # Shell da aplicação (abas, telas, diálogos)
│   ├── css/                         # Estilos
│   │   ├── style.css                # Folha principal: tokens, componentes, telas (11 seções)
│   │   ├── gemeo.css                # Estilos da aba Gêmeo 3D (5 seções)
│   │   └── command-center.css       # Identidade visual "Industrial Command Center" (6 seções)
│   └── js/                          # Lógica do front-end
│       ├── app.js                   # Ponto de entrada: monta as telas, liga eventos
│       ├── nucleo.js                # Roteamento de abas, estado global, ciclo de vida, toasts
│       ├── api.js                   # fetch padronizado (cookie + CSRF + JSON)
│       ├── conexao_ui.js            # Ponto único de acesso ao WebUI (Arduino App Lab)
│       ├── tema.js                  # Tema claro/escuro (preferência no localStorage)
│       ├── util.js                  # DOM, textos, datas, pílulas, localStorage
│       ├── grafico.js               # Gráficos SVG puros (linha + rosca)
│       ├── cenas.js                 # Cenas e caixas de detecção (vários trabalhadores)
│       ├── tela_bloqueio.js         # Login/logout com fallback legado (socket)
│       ├── tela_ao_vivo.js          # Tela "Ao vivo": vídeo, logs, KPIs, área de risco
│       ├── tela_ocorrencias.js      # Tela "Ocorrências": fila, filtros, detalhe, revisão, CSV, replay
│       ├── tela_painel.js           # Tela "Painel": KPIs, série diária, rosca, mini fila
│       ├── tela_gemeo.js            # Carregamento sob demanda do Gêmeo 3D (aba)
│       └── gemeo/                   # Módulos do Gêmeo 3D
│           ├── fonte_dados.js       # Normalizador de payloads, validação, reconexão (3 seções)
│           ├── interface.js         # Abas laterais, PiP do CCTV, espelhos (4 seções)
│           └── motor.js             # Núcleo 3D: 8 subsistemas (índice no topo)
│
├── tools/                           # Ferramentas de linha de comando
│   ├── avaliar_experimento.py       # Avaliação automática de experimentos (métricas, saída JSON)
│   └── ws_teste_gemeo.py            # Teste WebSocket para o Gêmeo 3D (envia quadros simulados)
│
├── tests/                           # Testes
│   ├── conftest.py                  # Fixtures compartilhadas (banco temporário, cliente HTTP)
│   ├── test_pipeline.py             # Testes do pipeline (detector, banco, assistente, servidor)
│   ├── test_amostragem.py           # Testes da métrica Pessoa-Frame
│   ├── test_painel.py               # Testes do painel (API, dashboard, conformidade)
│   ├── test_seguranca.py            # Testes de segurança (hash, sessão, CSRF, rate-limit)
│   ├── js/                          # Testes JavaScript
│   │   ├── test_fonte_dados.js      # Testes do normalizador de payloads (10 testes)
│   │   └── test_fonte_dados.cjs     # Mesmos testes em CommonJS
│   └── package.json                 # Configuração dos testes JS
│
└── docs/                            # Documentação
    ├── api.md                       # Documentação da API REST
    ├── arquitetura.md               # Documentação da arquitetura
    ├── metodologia.md               # Metodologia do TCC
    ├── redesign_visual.md           # Documentação do redesign visual
    └── mapa_codigo.md               # Este arquivo
```

---

## 2. Tabela de Referência Rápida

### 2.1. Quando quiser mexer em...

| Funcionalidade | Arquivo | Seção / Função |
|---|---|---|
| **Detecção de EPIs** | `python/detector.py` | §2: `verificar_epi()`, `classificar_infracao()` |
| **Área de risco** | `python/detector.py` | §2: `verificar_area_risco()`, `analisar_seguranca()` |
| **Projeção 2D→Planta** | `python/detector.py` | §3: `projetar_pe_para_planta()` |
| **Rastreamento (trilhas)** | `python/detector.py` | §4: `associar_trilhas()`, `calcular_iou()` |
| **Trajetória (buffer circular)** | `python/detector.py` | §5: `_ponto_trajetoria()`, `_amostrar_trajetoria()` |
| **Pipeline principal** | `python/detector.py` | §6: `organizar_dado()`, `filtrar_salvamento()` |
| **Callback da câmera** | `python/detector.py` | `operario_detectado()` (final do arquivo) |
| **Inicialização do App** | `python/main.py` | Início do arquivo |
| **Loop da câmera** | `python/main.py` | Loop principal (while True) |
| **Rotas REST** | `python/servidor.py` | §3: `ui.expose_api(...)` (todas as rotas) |
| **Telemetria 5 Hz** | `python/servidor.py` | §1: `enviar_telemetria()` |
| **Snapshot** | `python/servidor.py` | §2: `_snapshot` + `GET /snapshot` |
| **Calibração** | `python/servidor.py` | §2: `_get_calibracao`, `_post_calibracao` |
| **Banco SQLite** | `python/banco.py` | §1: `_garantir_tabelas()`, `_abrir_banco()` |
| **Ocorrências (CRUD)** | `python/banco.py` | §2: `salvar_cena()`, `dados_ocorrencias()`, `excluir_ocorrencia()` |
| **Revisão manual** | `python/banco.py` | §2: `revisar_ocorrencia()` |
| **Trajetórias (Replay 3D)** | `python/banco.py` | §3: `obter_trajetoria()`, `salvar_pontos_trajetoria()` |
| **Retenção 90 dias** | `python/banco.py` | §3: `limpar_trajetoria_antiga()` |
| **Mapa de calor** | `python/banco.py` | §4: `registrar_exposicao_celulas()`, `obter_mapa_calor()` |
| **Dashboard (agregações)** | `python/banco.py` | §5: `calcular_dados_dashboard()`, `_limites_periodo()` |
| **Métrica Pessoa-Frame** | `python/amostragem.py` | §1-§2: `registrar()`, `descarregar()`, `resumo()` |
| **Login / Sessão** | `python/seguranca.py` | §3: `login()`, `exigir()`, `sessao()`, `logout()` |
| **Hash de senha** | `python/seguranca.py` | §1: `gerar_hash()`, `_conferir()` |
| **Assistente IA** | `python/assistente.py` | §3: `responder()`, `_categoria()`, `_tentar_proxy()` |
| **Configurações globais** | `python/config.py` | Variáveis no topo do arquivo |
| **Roteamento de abas** | `assets/js/nucleo.js` | §2: `irPara()`, `registrarTela()` |
| **Estado global** | `assets/js/nucleo.js` | §1: `estado` |
| **Toasts (avisos)** | `assets/js/nucleo.js` | §4: `avisar()` |
| **Fetch REST** | `assets/js/api.js` | §1: `api()`, `apiJson()` |
| **WebUI (socket)** | `assets/js/conexao_ui.js` | `ui = new WebUI()` |
| **Tema claro/escuro** | `assets/js/tema.js` | `aplicar()`, `alternarTema()` |
| **Utilitários DOM** | `assets/js/util.js` | §1-§5: `el()`, `icone()`, `normalizar()`, `pilulaTipo()`, `lerPreferencia()` |
| **Gráficos SVG** | `assets/js/grafico.js` | §1: `desenharLinha()`, §2: `desenharRosca()` |
| **Cenas (múltiplos trabalhadores)** | `assets/js/cenas.js` | §2: `agruparCenas()`, §4: `desenharCaixas()` |
| **Login (tela)** | `assets/js/tela_bloqueio.js` | §2: `entrarPeloSocket()`, §3: `sair()` |
| **Ao vivo (tela)** | `assets/js/tela_ao_vivo.js` | §2: `log_deteccao()`, §3: `definirArea()` |
| **Ocorrências (tela)** | `assets/js/tela_ocorrencias.js` | §1-§7: `carregarOcorrencias()`, `criarItemCena()`, `revisarAtual()` |
| **Painel (tela)** | `assets/js/tela_painel.js` | §2: `carregarPainel()`, `desenhar()`, `contar()` |
| **Gêmeo 3D (tela)** | `assets/js/tela_gemeo.js` | §2: `iniciar()`, `pararGemeo()` |
| **Fonte de dados (Gêmeo)** | `assets/js/gemeo/fonte_dados.js` | §2: `normalizarMensagem()`, §3: `criarFonte()` |
| **Interface do Gêmeo** | `assets/js/gemeo/interface.js` | §1: `showTab()`, §2: `renderBadge()`, §4: `setPip()` |
| **Motor 3D (Gêmeo)** | `assets/js/gemeo/motor.js` | 8 subsistemas (ver índice no topo) |

### 2.2. Rotas REST

| Rota | Método | Arquivo | Função |
|---|---|---|---|
| `/login` | POST | `servidor.py` | `seguranca.login()` |
| `/sessao` | GET | `servidor.py` | `seguranca.sessao()` |
| `/logout` | POST | `servidor.py` | `seguranca.logout()` |
| `/listar_ocorrencias` | GET | `servidor.py` | `_listar_ocorrencias` |
| `/revisar_ocorrencia` | POST | `servidor.py` | `_revisar_ocorrencia` |
| `/excluir_ocorrencia` | DELETE | `servidor.py` | `_excluir_ocorrencia` |
| `/snapshot` | GET | `servidor.py` | `_snapshot` |
| `/calibracao` | GET/POST | `servidor.py` | `_get_calibracao`, `_post_calibracao` |
| `/ocorrencia/{id}/trajetoria` | GET | `servidor.py` | `_trajetoria_ocorrencia` |
| `/mapa_calor` | GET | `servidor.py` | `_mapa_calor` |
| `/assistente` | POST | `servidor.py` | `_assistente` |
| `/dashboard_dados` | GET | `servidor.py` | `_dashboard_dados` |
| `/foto/{nome}` | GET | `servidor.py` | `_foto` |

### 2.3. Mensagens Socket.IO (WebUI)

| Mensagem | Direção | Arquivo | Handler |
|---|---|---|---|
| `area_marcada` | App → Backend | `servidor.py` | `on_message` |
| `limpar_box_risco` | App → Backend | `servidor.py` | `on_message` |
| `retornar_box_risco` | App → Backend | `servidor.py` | `on_message` |
| `auth` | App → Backend | `servidor.py` | `on_message` |
| `senha` | App → Backend | `servidor.py` | `on_message` (legado) |
| `liberado` | Backend → App | `tela_bloqueio.js` | `on_message` |
| `rejeitado` | Backend → App | `tela_bloqueio.js` | `on_message` |
| `box_risco` | Backend → App | `tela_ao_vivo.js` | `on_message` |
| `log_deteccao` | Backend → App | `tela_ao_vivo.js` | `on_message` |
| `telemetria_gemeo` | Backend → App | `tela_gemeo.js` | `on_message` |
| `nova-ocorrencia` | App → App | `tela_ocorrencias.js` | `addEventListener` |
| `ocorrencias-atualizadas` | App → App | `tela_ocorrencias.js` | `dispatchEvent` |
| `sessao-expirada` | App → App | `tela_bloqueio.js` | `dispatchEvent` |

---

## 3. Diagrama do Fluxo de Dados

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           FLUXO DE DADOS PASSO A PASSO                          │
│                     (da câmera até o banco SQLite e o Gêmeo 3D)                 │
└─────────────────────────────────────────────────────────────────────────────────┘

  ┌─────────────┐      ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
  │   CÂMERA    │      │  DETECTOR    │      │   SERVIDOR   │      │    BANCO     │
  │  (USB/IP)   │ ───► │  (Python)    │ ───► │  (FastAPI)   │ ───► │  (SQLite)    │
  └─────────────┘      └──────────────┘      └──────────────┘      └──────────────┘
        │                    │                      │                      │
        │ 1. Frame JPEG      │ 2. Pessoas + EPIs    │ 3. Ocorrências       │ 4. Persistência
        │    (640x480)       │    (bbox, EPIs,     │    (REST + Socket)   │    (tabelas)
        │                    │    área de risco)    │                      │
        │                    │                      │                      │
        ▼                    ▼                      ▼                      ▼
  ┌─────────────┐      ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
  │   INPUT     │      │  detecção    │      │  WebUI       │      │  tabelas:    │
  │  Frame bruto│      │ Operario    │      │  (socket.io) │      │  ocorrencias │
  │  (JPEG)     │      │  (dataclass) │      │              │      │  trajetoria  │
  └─────────────┘      └──────────────┘      └──────────────┘      │  exposicao_  │
                                                                     │  celula      │
                                                                     └──────────────┘

  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                         BACKEND (Python)                                     │
  ├─────────────────────────────────────────────────────────────────────────────┤
  │                                                                              │
  │  main.py:                                                                    │
  │  ┌─────────────────────────────────────────────────────────────────────┐    │
  │  │ 1. Inicializa WebUI (socket.io) + App Lab                            │    │
  │  │ 2. Inicia câmera (detector.on_detect_all)                            │    │
  │  │ 3. Loop: recebe frame -> chama operario_detectado()                  │    │
  │  └─────────────────────────────────────────────────────────────────────┘    │
  │                                    │                                         │
  │                                    ▼                                         │
  │  detector.py:                                                                │
  │  ┌─────────────────────────────────────────────────────────────────────┐    │
  │  │ 1. Verifica EPIs (capacete, colete)                                  │    │
  │  │ 2. Verifica área de risco (ponto dos pés)                            │    │
  │  │ 3. Projeta 2D → Planta 3D (homografia)                               │    │
  │  │ 4. Associa trilhas (IoU + distância + margem ambiguidade)            │    │
  │  │ 5. Buffer circular ±15s (2 Hz)                                        │    │
  │  │ 6. Acumula exposição por célula (80x60)                               │    │
  │  │ 7. montar_cena() → lista de registros                                 │    │
  │  └─────────────────────────────────────────────────────────────────────┘    │
  │                                    │                                         │
  │                                    ▼                                         │
  │  servidor.py:                                                                │
  │  ┌─────────────────────────────────────────────────────────────────────┐    │
  │  │ 1. enviar_telemetria() → socket.io (5 Hz)                            │    │
  │  │ 2. atualizar_ultimo_frame() → snapshot                               │    │
  │  │ 3. Rotas REST (FastAPI):                                              │    │
  │  │    GET  /listar_ocorrencias → banco.dados_ocorrencias()             │    │
  │  │    POST /revisar_ocorrencia → banco.revisar_ocorrencia()            │    │
  │  │    GET  /dashboard_dados  → banco.calcular_dados_dashboard()        │    │
  │  │    GET  /mapa_calor       → banco.obter_mapa_calor()                │    │
  │  │    POST /assistente       → assistente.responder()                  │    │
  │  │    GET  /ocorrencia/{id}/trajetoria → banco.obter_trajetoria()      │    │
  │  └─────────────────────────────────────────────────────────────────────┘    │
  │                                    │                                         │
  │                                    ▼                                         │
  │  banco.py:                                                                   │
  │  ┌─────────────────────────────────────────────────────────────────────┐    │
  │  │ 1. inicializar_banco() → cria tabelas (migração idempotente)        │    │
  │  │ 2. salvar_cena() → 1 foto + N ocorrências (x_m, z_m, celula_idx)    │    │
  │  │ 3. salvar_pontos_trajetoria() → ±15s por ocorrência                  │    │
  │  │ 4. registrar_exposicao_celulas() → incrementa exposição              │    │
  │  │ 5. limpar_trajetoria_antiga(90 dias) → retenção                       │    │
  │  │ 6. calcular_dados_dashboard() → agregações do painel                 │    │
  │  └─────────────────────────────────────────────────────────────────────┘    │
  │                                                                              │
  └─────────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                         FRONTEND (JavaScript)                                │
  ├─────────────────────────────────────────────────────────────────────────────┤
  │                                                                              │
  │  app.js:                                                                     │
  │  ┌─────────────────────────────────────────────────────────────────────┐    │
  │  │ 1. Carrega tema.js (preferência)                                     │    │
  │  │ 2. Liga abas (#abas [data-tela]) -> irPara()                         │    │
  │  │ 3. Inicia fluxo de acesso (tela_bloqueio.js)                         │    │
  │  │ 4. Inicia telas: Ao vivo, Ocorrências, Painel                        │    │
  │  └─────────────────────────────────────────────────────────────────────┘    │
  │                                    │                                         │
  │                                    ▼                                         │
  │  nucleo.js:                                                                  │
  │  ┌─────────────────────────────────────────────────────────────────────┐    │
  │  │ 1. estado = { tela, autenticado }                                    │    │
  │  │ 2. registrarTela(nome, { entrar })                                   │    │
  │  │ 3. irPara(nome, { historico, foco })                                 │    │
  │  │ 4. mostrarBloqueio(sim) / definirChip(id, situacao, texto)           │    │
  │  │ 5. avisar(texto, { tipo, acao, duracao })                           │    │
  │  └─────────────────────────────────────────────────────────────────────┘    │
  │                                    │                                         │
  │                                    ▼                                         │
  │  Telas:                                                                      │
  │  ┌─────────────────────────────────────────────────────────────────────┐    │
  │  │ tela_bloqueio.js: POST /login -> cookie -> socket "auth"            │    │
  │  │ tela_ao_vivo.js:   socket "log_deteccao" -> lista + KPIs            │    │
  │  │                    canvas #area-risco -> "area_marcada"             │    │
  │  │ tela_ocorrencias.js: GET /listar_ocorrencias -> cenas                │    │
  │  │                      POST /revisar_ocorrencia -> atualiza             │    │
  │  │                      GET /ocorrencia/{id}/trajetoria -> replay 3D   │    │
  │  │ tela_painel.js:     GET /dashboard_dados -> KPIs + gráficos         │    │
  │  │ tela_gemeo.js:      socket "telemetria_gemeo" -> GemeloPonte        │    │
  │  │ assistente.js:     POST /assistente -> resposta + ações             │    │
  │  └─────────────────────────────────────────────────────────────────────┘    │
  │                                    │                                         │
  │                                    ▼                                         │
  │  Gêmeo 3D:                                                                   │
  │  ┌─────────────────────────────────────────────────────────────────────┐    │
  │  │ 1. tela_gemeo.js carrega sob demanda:                                 │    │
  │  │    - libs/three.min.js                                               │    │
  │  │    - js/gemeo/fonte_dados.js (normalizador)                          │    │
  │  │    - js/gemeo/motor.js (8 subsistemas)                               │    │
  │  │    - js/gemeo/interface.js (abas, PiP, espelhos)                     │    │
  │  │                                                                       │    │
  │  │ 2. motor.js (8 subsistemas):                                         │    │
  │  │    §1. Escala e Estado (W=320, H=240, B=4, grade 80x60)              │    │
  │  │    §2. Visão Computacional 2D (scanPlan, limiar adaptativo)           │    │
  │  │    §3. Construção 3D (initTwin, buildScene, greedy meshing)          │    │
  │  │    §4. Pool de Avatares (createWorker, totens Layer 2)               │    │
  │  │    §5. Câmeras PTZ (CAM 1A/1B/2A, CanvasTexture CCTV)                │    │
  │  │    §6. Mapa de Calor (heatGrid, replay caixa-preta)                   │    │
  │  │    §7. Calibrador Homografia (4 cliques, matriz H)                    │    │
  │  │    §8. Ponte de Dados + Loop (setRealData, animate)                   │    │
  │  │                                                                       │    │
  │  │ 3. fonte_dados.js:                                                    │    │
  │  │    - Normaliza payloads (3 formatos)                                  │    │
  │  │    - Valida (num, fin, conf, bool)                                    │    │
  │  │    - Reconexão com backoff                                            │    │
  │  │    - API: normalizarMensagem, criarFonte                              │    │
  │  └─────────────────────────────────────────────────────────────────────┘    │
  │                                    │                                         │
  │                                    ▼                                         │
  │  interface.js:                                                               │
  │  ┌─────────────────────────────────────────────────────────────────────┐    │
  │  │ 1. Abas laterais (plan/log/workers)                                   │    │
  │  │ 2. Contadores (eventos, operários) via MutationObserver               │    │
  │  │ 3. Espelhos (KPI -> resumo)                                           │    │
  │  │ 4. Painel lateral + PiP do CCTV (min/mid/max)                         │    │
  │  └─────────────────────────────────────────────────────────────────────┘    │
  │                                                                              │
  └─────────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                         FLUXO DE DADOS (DETALHADO)                           │
  ├─────────────────────────────────────────────────────────────────────────────┤
  │                                                                              │
  │  1. CÂMERA → DETECTOR                                                        │
  │     ──────────────────────                                                     │
  │     - Frame JPEG (640x480) via on_detect_all                                │
  │     - operario_detectado(frame, deteccoes)                                   │
  │                                                                              │
  │  2. DETECTOR → SERVIDOR                                                      │
  │     ─────────────────────                                                      │
  │     - analisar_seguranca() → lista de Operario                               │
  │     - filtrar_salvamento() → registros válidos (com cooldown)               │
  │     - montar_cena() → cena completa (todos os trabalhadores)                │
  │     - enviar_telemetria() → socket.io (5 Hz)                                │
  │     - atualizar_ultimo_frame() → snapshot (JPEG)                            │
  │                                                                              │
  │  3. SERVIDOR → BANCO                                                         │
  │     ─────────────────────                                                      │
  │     - salvar_cena(frame, registros, cena)                                    │
  │       → 1 foto em PASTA_FOTOS                                                │
  │       → N linhas em ocorrencias (com x_m, z_m, celula_idx)                  │
  │       → caixas JSON com cena_id + lista de operarios                        │
  │     - salvar_pontos_trajetoria(ocorrencia_id, pontos)                       │
  │       → tabela trajetoria (±15s por ocorrência)                              │
  │     - registrar_exposicao_celulas(incrementos)                               │
  │       → tabela exposicao_celula (80x60)                                      │
  │                                                                              │
  │  4. BANCO → SERVIDOR (LEITURA)                                               │
  │     ─────────────────────────────                                            │
  │     - GET /listar_ocorrencias → dados_ocorrencias()                         │
  │     - GET /dashboard_dados → calcular_dados_dashboard(dias)                 │
  │     - GET /mapa_calor → obter_mapa_calor()                                  │
  │     - GET /ocorrencia/{id}/trajetoria → obter_trajetoria(id)                │
  │     - POST /assistente → assistente.responder(pergunta)                     │
  │     - GET /snapshot → _snapshot (último frame JPEG)                         │
  │     - GET/POST /calibracao → _get_calibracao / _post_calibracao             │
  │                                                                              │
  │  5. SERVIDOR → FRONTEND                                                      │
  │     ─────────────────────────                                                │
  │     - socket.io: telemetria_gemeo (5 Hz)                                    │
  │     - REST: respostas JSON (apiJson)                                        │
  │     - Snapshot: image/jpeg (thumbnail)                                      │
  │     - Calibração: GET/POST JSON                                             │
  │                                                                              │
  │  6. FRONTEND → GÊMEO 3D                                                      │
  │     ─────────────────────────                                                │
  │     - tela_gemeo.js carrega módulos sob demanda                             │
  │     - GemeloPonte.receber(payload) → fonte_dados.normalizarMensagem()       │
  │     - motor.js consome quadros normalizados                                 │
  │     - interface.js renderiza abas, PiP, espelhos                           │
  │     - Replay: tela_ocorrencias.js chama GemeloPonte.reproduzir(id)          │
  │                                                                              │
  │  7. GÊMEO 3D → BANCO (REPLAY)                                                │
  │     ─────────────────────────────                                            │
  │     - GET /ocorrencia/{id}/trajetoria → motor.reproduzirTrilha(pontos)      │
  │     - Animação temporal (playReplay)                                        │
  │                                                                              │
  │  8. ASSISTENTE IA                                                            │
  │     ─────────────                                                            │
  │     - POST /assistente { pergunta }                                         │
  │     - assistente.responder() → _categoria() → motor local                   │
  │     - (Opcional) _tentar_proxy() → LLM externo (ASSISTENTE_LLM_URL)         │
  │     - Resposta: { resposta, fonte, acoes }                                  │
  │                                                                              │
  │  9. SEGURANÇA                                                                │
  │     ──────────                                                               │
  │     - Login: PBKDF2 (TCC_SENHA_HASH) + cookie HttpOnly                      │
  │     - Sessão: _sessoes (memória) + tickets                                  │
  │     - CSRF: x-requested-with: painel                                        │
  │     - Rate-limit: _falhas (por IP)                                          │
  │                                                                              │
  │ 10. AMOSTRAGEM                                                               │
  │     ──────────                                                               │
  │     - registrar(operarios, area_ativa) → baldes por minuto                 │
  │     - descarregar() → grava em SQLite (amostras_minuto)                    │
  │     - resumo() → taxas agregadas (conformidade, capacete, colete)          │
  │                                                                              │
  └─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Como Usar Este Mapa

- **Para encontrar onde implementar uma funcionalidade:** consulte a Tabela de Referência Rápida (§2.1).
- **Para entender o fluxo de dados:** siga o Diagrama do Fluxo de Dados (§3).
- **Para navegar na árvore de arquivos:** use a Árvore de Diretórios Comentada (§1).
- **Para rotas REST:** consulte §2.2.
- **Para mensagens Socket.IO:** consulte §2.3.

---

*Documento gerado automaticamente como parte da etapa de Organização Interna e Clareza de Código.*