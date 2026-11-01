# 🛡️ Painel de Monitoramento e Detecção de EPIs

Sistema autônomo embarcado de monitoramento em tempo real, auditoria e gestão de Equipamentos de Proteção Individual (**EPIs**) — com detecção simultânea de **Capacete** e **Colete Refletivo** — e fiscalização dinâmica de **Área de Risco**. Desenvolvido para a placa **Arduino UNO Q** através do ecossistema **Arduino App Lab**, combinando inferência neural local via **YOLOv11n** (Edge Impulse), backend assíncrono em **Python** (FastAPI / WebSockets) e uma interface web moderna do tipo Single Page Application (**SPA**) em Vanilla JavaScript modular.

---

## 📋 Sumário

- [Visão Geral](#-visão-geral)
- [Principais Funcionalidades](#-principais-funcionalidades)
- [Hardware e Plataforma Embarcada](#-hardware-e-plataforma-embarcada)
- [Estrutura Completa de Diretórios](#-estrutura-completa-de-diretórios)
- [Engenharia e Arquitetura do Pipeline](#-engenharia-e-arquitetura-do-pipeline)
  - [1. Fluxo de Processamento de Dados](#1-fluxo-de-processamento-de-dados)
  - [2. Ponto de Entrada (`main.py`)](#2-ponto-de-entrada-mainpy)
  - [3. Detecção, Associação Anatômica e Tracking (`detector.py`)](#3-detecção-associação-anatômica-e-tracking-detectorpy)
  - [4. Autenticação e Segurança Criptográfica (`seguranca.py` & `config.py`)](#4-autenticação-e-segurança-criptográfica-segurancapy--configpy)
  - [5. Servidor de Aplicação e Barramento em Tempo Real (`servidor.py`)](#5-servidor-de-aplicação-e-barramento-em-tempo-real-servidorpy)
  - [6. Persistência, Armazenamento USB e Telemetria (`banco.py`)](#6-persistência-armazenamento-usb-e-telemetria-bancopy)
- [Modelagem do Banco de Dados SQLite](#-modelagem-do-banco-de-dados-sqlite)
- [Interface do Usuário (Frontend SPA)](#-interface-do-usuário-frontend-spa)
  - [Fluxo de Telas e Navegação](#fluxo-de-telas-e-navegação)
  - [Componentes e Recursos Visuais](#componentes-e-recursos-visuais)
  - [Sprite de Ícones Vetoriais SVG](#sprite-de-ícones-vetoriais-svg)
- [Protocolos de Comunicação e APIs](#-protocolos-de-comunicação-e-apis)
  - [Rotas HTTP REST (FastAPI)](#rotas-http-rest-fastapi)
  - [Mensageria WebSocket (`WebUI`)](#mensageria-websocket-webui)
  - [Padronização dos Logs do Sistema](#padronização-dos-logs-do-sistema)
- [Guia de Configuração e Execução](#-guia-de-configuração-e-execução)
  - [Pré-requisitos](#pré-requisitos)
  - [Configuração de Credenciais](#configuração-de-credenciais)
  - [Executando no Arduino App Lab](#executando-no-arduino-app-lab)
  - [Ajustes e Calibração de Parâmetros](#ajustes-e-calibração-de-parâmetros)
- [Autoria e Créditos](#-autoria-e-créditos)

---

## 🎯 Visão Geral

O projeto tem como missão elevar a conformidade com as normas regulamentadoras de segurança do trabalho (notadamente a **NR-6**) em canteiros de obras e plantas industriais. Através da automação inteligente por visão computacional, o sistema atua como uma barreira preventiva contra acidentes graves, mitigando falhas humanas na fiscalização.

O sistema opera **100% no dispositivo (Edge Computing)**, executando a inferência neural, a validação geométrica de conformidade, a gestão de banco de dados e a disponibilização da interface web localmente na placa Arduino UNO Q, sem depender de conexão com nuvem ou serviços externos.

---

## ✨ Principais Funcionalidades

- **Detecção Simultânea de Múltiplas Classes**: Identifica operários (`person`), capacetes de proteção (`helmet`) e coletes refletivos (`vest`).
- **Validação Anatômica Espacial**: Algoritmo geométrico que restringe a validação do capacete à região da cabeça/testa e do colete à região do tronco, associando o EPI ao operário mais próximo via distância euclidiana.
- **Demarcação Dinâmica de Área de Risco**: Ferramenta interativa no frontend onde o operador clica e arrasta sobre a transmissão de vídeo para delimitar uma zona perigosa retangular em tempo real.
- **Rastreamento Multi-operário (Tracking Temporal)**: Identifica e associa cada operário por ID único entre quadros consecutivos por distância euclidiana de centroides ($\le 90$ px), expurgando cadastros inativos após 20 segundos de ausência.
- **Cooldown Inteligente de Persistência**: Evita saturação do armazenamento físico e gravações em rajada, aplicando um intervalo mínimo de 20 segundos entre salvamentos para um mesmo indivíduo rastreado.
- **Registro Fotográfico e Telemetria Completa**: Salva o quadro exato da infração em JPEG acompanhado das coordenadas espaciais, pontuações de confiança e carimbo de data/hora (ISO 8601).
- **Classificação em 4 Categorias de Ocorrência**: Registra com precisão estados seguros e violações:
  1. `Seguro, todos os EPIs detectados`
  2. `Sem colete`
  3. `Sem capacete`
  4. `Sem capacete e colete`
- **Segurança Criptográfica Robusta**: Autenticação com derivação de chave **`scrypt`** (salt aleatório de 16 bytes via `os.urandom`) e comparação em tempo constante (`secrets.compare_digest`), prevenindo ataques de força bruta e *timing attacks*.
- **Isolamento de Sessões por Sala**: O desbloqueio de acesso via WebSocket utiliza `room=cliente`, garantindo que apenas a estação autenticada receba a liberação da interface.
- **Painel Analítico de Conformidade (Dashboard)**:
  - 4 cartões de KPIs: Total de Observações, Tipos de Infração Registrados, Infração Mais Comum e Data/Hora da Última Ocorrência.
  - Gráfico em rosca (**Chart.js**) com distribuição quantitativa e percentual.
  - Tabela com histórico detalhado e paginação visual dos eventos recentes.
- **Galeria de Evidências Fotográficas**:
  - Miniaturas com selos de status e data/hora.
  - Modal de inspeção com projeção da **bounding box** do operário sobreposta proporcionalmente à resolução nativa (720×480).
  - Barras dinâmicas de confiança com categorização por faixa percentual (Alta $\ge 75\%$, Média $\ge 50\%$, Baixa $< 50\%$).
  - Exclusão física da imagem e remoção do registro no banco com diálogo modal de confirmação e alerta de status.
- **Transmissão de Vídeo e Feed de Logs**: Stream de baixa latência na porta `4912` e console lateral de logs transmitido via WebSockets.

---

## 🖥️ Hardware e Plataforma Embarcada

| Componente | Especificação | Descrição |
| :--- | :--- | :--- |
| **Placa** | Arduino UNO Q | Plataforma computacional embarcada que executa o sistema operacional, inferência e serviços web. |
| **Ambiente de Execução** | Arduino App Lab | Orquestrador de contêineres e ciclo de vida dos módulos (bricks) da aplicação. |
| **Bricks Ativos** | `arduino:video_object_detection`<br>`arduino:web_ui` | Bloco de visão computacional acelerada e servidor da interface de usuário (`app.yaml`). |
| **Modelo de IA** | `ei-model-1127250-2` | Rede neural YOLOv11n compilada e otimizada via Edge Impulse para detecção de operários, capacetes e coletes. |
| **Câmera** | Câmera USB (índice `0`) | Resolução nativa de captura: **720×480** pixels a **10 FPS** com pré-visualização ativa. |
| **Armazenamento Externo** | Pendrive USB (`/app/pendrive`) | Unidade de montagem obrigatória contendo o banco SQLite (`seguranca.db`) e o repositório de fotos (`evidencias/`). |

---

## 📁 Estrutura Completa de Diretórios

```text
Projeto-TCC/
├── app.yaml                        # Definição e configuração dos bricks do Arduino App Lab
├── README.md                       # Documentação técnica e operacional do projeto
├── .gitignore                      # Regras de exclusão do Git (ignora /python/config.py)
├── python/                         # Backend em Python (lógica, detecção e serviços)
│   ├── main.py                     # Ponto de entrada da aplicação — orquestração e App.run()
│   ├── config.py                   # Armazena a credencial em texto puro (não versionado)
│   ├── config.example.py           # Template de referência para criação do config.py
│   ├── seguranca.py                # Criptografia scrypt, salt aleatório e compare_digest
│   ├── detector.py                 # Pipeline de vídeo, inferência YOLO, zonas anatômicas e tracking
│   ├── servidor.py                 # Instância WebUI, endpoints FastAPI e despachante de eventos
│   └── banco.py                    # Gestão do SQLite, verificação do pendrive e agregação de KPIs
└── assets/                         # Frontend da Interface Web (Single Page Application)
    ├── index.html                  # Marcação estrutural das 4 telas principais e modais
    ├── icones.svg                  # Sprite com 17 ícones vetoriais SVG reutilizáveis
    ├── css/
    │   └── style.css               # Folha de estilos moderna (tema escuro industrial e responsividade)
    ├── js/
    │   ├── app.js                  # Ponto central do JS, roteamento entre telas e bootstrap
    │   ├── conexao_ui.js           # Instanciação compartilhada da conexão WebUI (Socket.IO)
    │   ├── tela_bloqueio.js        # Lógica de login, submissão de senha e feedback de erro
    │   ├── tela_camera.js          # Incorporação do stream de vídeo e receptor de logs
    │   ├── tela_canvas.js          # Captura e desenho interativo do retângulo de área de risco
    │   ├── tela_dashboard.js       # Carregamento de métricas, cards de KPI, gráfico Chart.js e tabela
    │   ├── tela_galeria.js         # Grade de evidências, desenho da caixa do operário e exclusão
    │   └── utils/
    │       ├── formatarCoord.js    # Utilitário de formatação de coordenadas numéricas (1 casa decimal)
    │       └── formatarDataHora.js # Conversão de carimbos ISO para formato local brasileiro (pt-BR)
    └── libs/                       # Dependências estáticas de terceiros embutidas localmente
        ├── arduino.js              # Camada cliente de comunicação WebUI do Arduino App Lab
        ├── chart.umd.min.js        # Chart.js para renderização dos gráficos analíticos
        └── socket.io.min.js        # Biblioteca cliente do Socket.IO
```

---

## ⚙️ Engenharia e Arquitetura do Pipeline

### 1. Fluxo de Processamento de Dados

```text
       [ Câmera USB 720×480 @ 10 FPS ]
                      │
                      ▼
   [ Brick: VideoObjectDetection (YOLOv11n) ] ──> HTTP Stream (:4912/embed) ──> [ Iframe UI ]
                      │
                      ▼ Callback com specs_frame (person, helmet, vest)
            [ detector.py: organizar_dado ]
        ┌─────────────┴─────────────────────────┐
        ▼                                       ▼
  [ Validação Anatômica EPI ]            [ Área de Risco ]
  - Cabeça: [-15%, +35%]                 - Bounding box ativa
  - Tronco: [+36%, +80%]                 - Centroide contido?
        └─────────────┬─────────────────────────┘
                      ▼
        [ detector.py: analisar_seguranca ]
        - Emite logs em tempo real via WebSockets
        - Ativa flag global salvar_imagem se houver risco/infração
                      │
                      ▼
        [ detector.py: rastrear_operarios ]
        - Centroide euclidiano (DISTANCIA_MAXIMA = 90 px)
        - Limpeza de inatividade (> 20 segundos)
        - Cooldown de persistência (> 20 segundos por ID)
                      │
                      ▼ (Se salvar_imagem ativa e cooldown liberado)
        [ detector.py: filtrar_salvamento ]
                      │
                      ▼
        [ banco.py: salvar_ocorrencias ]
        ├── Valida pendrive montado (/app/pendrive)
        ├── Grava JPEG em /app/pendrive/evidencias/
        └── Insere registro na tabela SQLite 'ocorrencias'
                      │
                      ▼
        [ Servidor FastAPI / WebSockets ] ───> [ Interface Web SPA ]
```

---

### 2. Ponto de Entrada (`main.py`)

O módulo [`python/main.py`](file:///d:/VSCode/Repositorios%20GitHub/Lucas/Projeto-TCC/Projeto-TCC/python/main.py) atua como orquestrador de inicialização do ciclo de vida da aplicação. Ele importa sequencialmente os submódulos do sistema (`detector`, `config`, `seguranca`, `servidor`, `banco`) garantindo o registro de manipuladores de eventos e endpoints da API antes de ceder o controle da thread ao orquestrador do Arduino através de `App.run()`.

```python
from arduino.app_utils import App
import detector
import config
import seguranca
import servidor
import banco

App.run()
```

---

### 3. Detecção, Associação Anatômica e Tracking (`detector.py`)

O módulo [`python/detector.py`](file:///d:/VSCode/Repositorios%20GitHub/Lucas/Projeto-TCC/Projeto-TCC/python/detector.py) contém a inteligência de validação espacial e rastreamento contínuo:

#### Configuração de Hardware da Câmera
- Instancia `Camera(source=0, resolution=(720, 480), fps=10)`.
- Instancia `VideoObjectDetection` com modelo configurado no `app.yaml`, `debounce_sec=0`, `confidence=0.5` e `camera_preview=True` (expondo o stream de visualização com os bounding boxes detectados na porta `4912`).

#### Modelagem em Memória (`Operario`)
Cada operário identificado no quadro é representado pela estrutura de dados:
```python
@dataclass
class Operario:
    box_xyxy: tuple
    id: int | None = None
    tem_colete: bool = False
    tem_capacete: bool = False
    risco_detectado: bool = False
    conf_pessoa: float | None = None
    conf_capacete: float | None = None
    conf_colete: float | None = None
```

#### Regras Geométricas de Associação de EPIs
Para evitar que um capacete no chão ou na mão seja validado, ou que o EPI de um trabalhador seja incorretamente associado a outro próximo, o sistema calcula zonas anatômicas proporcionais à altura do operário ($H = |y_2 - y_1|$):

1. **Capacete (`helmet`)**:
   - **Faixa de Validação Vertical**: $\left[y_1 - 0{,}15 \cdot H,\; y_1 + 0{,}35 \cdot H\right]$ (permite ligeira tolerância acima do topo da cabeça até a linha superior do tórax).
   - **Ponto de Atração Alvo**: $y_{\text{alvo}} = y_1 + 0{,}10 \cdot H$ (altura da testa).
   - **Validação Horizontal**: $x_1 \le x_{\text{centro\_capacete}} \le x_2$.
2. **Colete Refletivo (`vest`)**:
   - **Faixa de Validação Vertical**: $\left[y_1 + 0{,}36 \cdot H,\; y_1 + 0{,}80 \cdot H\right]$ (região anatômica do tronco/abdômen).
   - **Ponto de Atração Alvo**: $y_{\text{alvo}} = y_1 + 0{,}55 \cdot H$ (centro do peito).
   - **Validação Horizontal**: $x_1 \le x_{\text{centro\_colete}} \le x_2$.

Havendo múltiplos operários compatíveis, o EPI é atribuído àquele que apresentar a menor distância euclidiana entre o centro do EPI e o ponto de atração alvo da região:
$$d = \sqrt{(x_{\text{EPI}} - x_{\text{operario}})^2 + (y_{\text{EPI}} - y_{\text{alvo}})^2}$$

#### Fiscalização de Área de Risco
A função `verificar_area_risco(box_risco, box_pessoa)` determina se o centroide da base/corpo do operário $\left(\frac{px_1 + px_2}{2}, \frac{py_1 + py_2}{2}\right)$ está geometricamente contido dentro dos limites do retângulo demarcado pelo operador:
$$rx_1 \le \text{centro}_x \le rx_2 \quad \land \quad ry_1 \le \text{centro}_y \le ry_2$$

#### Algoritmo de Tracking e Cooldown
- **Associação de Centroides**: Associa caixas detectadas no quadro atual aos IDs registrados no dicionário `dados_operarios` caso a distância euclidiana seja menor que `DISTANCIA_MAXIMA = 90` pixels.
- **Descarte por Ausência**: Remove operários do rastreamento cuja última detecção tenha ocorrido há mais de 20 segundos ($t_{\text{atual}} - t_{\text{visto}} > 20\text{ s}$).
- **Intervalo de Persistência (Cooldown)**:
  - No primeiro registro do indivíduo (`ultimo_salvamento == 0`), dispara a persistência imediatamente e registra o timestamp atual.
  - Para detecções subsequentes do mesmo indivíduo, novas gravações só ocorrem se decorridos mais de 20 segundos ($t_{\text{atual}} - t_{\text{ultimo}} > 20\text{ s}$).

---

### 4. Autenticação e Segurança Criptográfica (`seguranca.py` & `config.py`)

A segurança do painel de controle adota práticas alinhadas às recomendações de criptografia moderna contra ataques de dicionário e *timing attacks*:

- **Leitura da Credencial**: A senha mestra é definida em `python/config.py` através da constante `SENHA_SALVA`.
- **Geração de Salt Criptográfico**: Na inicialização do módulo, gera um salt aleatório forte de 16 bytes via `os.urandom(16)`.
- **Derivação de Chave via `scrypt`**: O hash da senha mestra e de qualquer tentativa de login é calculado utilizando a função `hashlib.scrypt`:
  ```python
  hash_salvo = hashlib.scrypt(minha_senha, salt=salt_base_bytes, n=16384, r=8, p=1)
  ```
  - $N = 16384$: Custo de CPU e memória que dificulta ataques massivos por hardware dedicado (FPGA/ASIC).
  - $r = 8$: Tamanho de bloco da memória.
  - $p = 1$: Fator de paralelização.
- **Comparação em Tempo Constante**: A validação das tentativas submetidas utiliza `secrets.compare_digest(hash_tentativa, hash_salvo)`, neutralizando vazamento de tempo (*side-channel timing attacks*).

---

### 5. Servidor de Aplicação e Barramento em Tempo Real (`servidor.py`)

O módulo [`python/servidor.py`](file:///d:/VSCode/Repositorios%20GitHub/Lucas/Projeto-TCC/Projeto-TCC/python/servidor.py) integra o brick `WebUI` do Arduino, orquestrando tanto a comunicação orientada a eventos via WebSockets (Socket.IO) quanto as rotas HTTP assíncronas via FastAPI:

- **Isolamento de Sessão por Cliente**: A mensagem de validação de senha direciona a resposta especificamente para a sala do socket solicitante (`room=cliente`), impedindo que acessos concorrentes em diferentes dispositivos interfiram na sessão uns dos outros.
- **Estado Compartilhado da Área de Risco**: Mantém em variáveis de módulo (`box_risco`, `risco`) as coordenadas ativas da área delimitada na interface, compartilhadas diretamente com o módulo `detector.py`.
- **Distribuição de Logs**: Centraliza a emissão de mensagens de diagnóstico para o console do navegador através da função `enviar_log(mensagem)`.

---

### 6. Persistência, Armazenamento USB e Telemetria (`banco.py`)

O módulo [`python/banco.py`](file:///d:/VSCode/Repositorios%20GitHub/Lucas/Projeto-TCC/Projeto-TCC/python/banco.py) gerencia toda a camada de armazenamento físico e agregações analíticas:

- **Validação de Montagem do Pendrive**: Toda rotina de persistência valida se o pendrive USB está ativamente montado em `/app/pendrive` via `os.path.ismount(caminho_pendrive)`. Caso contrário, emite alerta e aborta a operação para não consumir a memória interna do microcontrolador.
- **Gravação de Imagens**: Salva os quadros em formato bruto JPEG em `/app/pendrive/evidencias/` com nomenclatura identificadora:
  `foto_{timestamp}_{tipo_infracao}_{posicao_operario}.jpg`
- **Sanitização de Caminhos**: Na rota de recuperação de fotos, utiliza `os.path.basename` para impedir ataques de travessia de diretório (*directory traversal*).
- **Motor de Agregação de KPIs**: A função `calcular_dados_dashboard()` compila em memória o total de observações, a distribuição quantitativa por tipo (`collections.Counter`), a taxa percentual de conformidade e o histórico ordenado decrescente.

---

## 🗄️ Modelagem do Banco de Dados SQLite

O banco de dados do sistema reside em `/app/pendrive/seguranca.db` e conta com a tabela `ocorrencias`:

```sql
CREATE TABLE IF NOT EXISTS ocorrencias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    tipo_infracao TEXT NOT NULL,
    caixa_operario TEXT NOT NULL,
    posicao_x REAL,
    posicao_y REAL,
    conf_pessoa REAL NULL,
    conf_capacete REAL NULL,
    conf_colete REAL NULL,
    caminho_foto TEXT
);
```

### Dicionário de Dados

| Coluna | Tipo | Nulo | Descrição |
| :--- | :---: | :---: | :--- |
| `id` | `INTEGER` | Não | Chave primária autoincrementada identificadora do registro. |
| `timestamp` | `TEXT` | Não | Data e hora da detecção no padrão ISO 8601 (`YYYY-MM-DDTHH:MM:SS`). |
| `tipo_infracao` | `TEXT` | Não | Classificação da ocorrência (`Seguro, todos os EPIs detectados`, `Sem colete`, `Sem capacete`, `Sem capacete e colete`). |
| `caixa_operario` | `TEXT` | Não | String JSON contendo o array com as coordenadas `[x1, y1, x2, y2]` da caixa do operário na resolução nativa. |
| `posicao_x` | `REAL` | Sim | Coordenada horizontal do centroide do operário em pixels: $(x_1 + x_2) / 2$. |
| `posicao_y` | `REAL` | Sim | Coordenada vertical do centroide do operário em pixels: $(y_1 + y_2) / 2$. |
| `conf_pessoa` | `REAL` | Sim | Pontuação de confiança da detecção da pessoa ($0.00$ a $1.00$). |
| `conf_capacete` | `REAL` | Sim | Pontuação de confiança da detecção do capacete atribuído ($0.00$ a $1.00$, ou `NULL`). |
| `conf_colete` | `REAL` | Sim | Pontuação de confiança da detecção do colete atribuído ($0.00$ a $1.00$, ou `NULL`). |
| `caminho_foto` | `TEXT` | Sim | Caminho absoluto do arquivo de imagem armazenado no pendrive. |

---

## 💻 Interface do Usuário (Frontend SPA)

A interface web foi projetada como uma Single Page Application moderna, responsiva e de alto contraste, desenvolvida em Vanilla JavaScript modular (ES6 Modules) sem a necessidade de empacotadores externos (*bundlers*).

### Fluxo de Telas e Navegação

```text
               ┌───────────────────────┐
               │    Tela de Bloqueio   │
               │   (#tela-bloqueio)    │
               └──────────┬────────────┘
                          │ Senha Correta
                          ▼
               ┌───────────────────────┐
  ┌──────────> │    Câmera ao Vivo     │ <─────────┐
  │ Bloquear   │    (#video-camera)    │           │ Voltar
  │            └──────────┬────────────┘           │
  │                       │ Clicar em "DashBoard"  │
  │                       ▼                        │
  │            ┌───────────────────────┐           │
  │            │   Painel Analítico    │ ──────────┘
  │            │      (#dashboard)     │ ◄─────────┐
  │            └──────────┬────────────┘           │ Voltar
  │                       │ Clicar em "Ver Fotos"  │
  │                       ▼                        │
  │            ┌───────────────────────┐           │
  │            │  Galeria de Imagens   │ ──────────┘
  │            │ (#capturas-infracoes) │
  │            └──────────┬────────────┘
  │                       │ Clicar em um Card
  │                       ▼
  │            ┌───────────────────────┐
  │            │   Modal de Detalhes   │
  │            │ (#mostrar-dados-imagem)
  │            └──────────┬────────────┘
  │                       │ Clicar em "Deletar"
  │                       ▼
  │            ┌───────────────────────┐
  └─────────── │ Confirmação de Delete │
               │  (#permissao-apagar)  │
               └───────────────────────┘
```

### Componentes e Recursos Visuais

1. **Tela de Bloqueio (`tela_bloqueio.js`)**:
   - Bloqueio inicial compulsório ao carregar a aplicação.
   - Suporte à submissão via botão ou tecla `Enter`.
   - Limpeza automática do campo de senha e mensagem de erro temporizada (2,5s) em caso de credencial inválida.
2. **Tela da Câmera ao Vivo (`tela_camera.js` & `tela_canvas.js`)**:
   - `<iframe>` integrado apontando para `http://${ipUnoq}:4912/embed`.
   - Canvas transparente sobreposto (`720×460`) permitindo desenhar retângulos com o mouse (`mousedown`, `mousemove`, `mouseup`).
   - Feedback visual do retângulo em verde translúcido (`rgba(0, 255, 0, 0.2)` com borda `#00FF00`).
   - Sincronização automática com a área já ativa no backend ao abrir a página (`DOMContentLoaded`).
   - Botão para limpar a área demarcada e botão de bloqueio rápido.
   - Console lateral de logs com rolagem contínua e botão para limpar histórico de mensagens.
3. **Painel Analítico / Dashboard (`tela_dashboard.js`)**:
   - 4 Cartões de KPI: Total de Observações, Tipos de Infração, Infração Mais Comum e Horário da Última Ocorrência.
   - Gráfico de Rosca interativo (**Doughnut Chart**) renderizado via Chart.js, colorido dinamicamente por tipo de evento.
   - Tabela de eventos recentes com ordenação decrescente e visualização das coordenadas e confiança.
4. **Galeria de Evidências Fotográficas (`tela_galeria.js`)**:
   - Grade responsiva de cartões com carregamento sob demanda (`loading="lazy"`).
   - Selo visual de câmera e rodapé contendo o ID, o tipo de evento e a data/hora formatada.
5. **Modal de Detalhes da Ocorrência**:
   - **Projeção Proporcional de Bounding Box**: Um canvas transparente sobreposto à imagem calcula a proporção entre a resolução nativa da captura (720×480) e as dimensões exibidas na tela, desenhando a caixa delimitadora do operário em vermelho (`#ff0000`, espessura 3px).
   - **Barras Dinâmicas de Confiança**: Exibe as pontuações para Pessoa, Capacete e Colete, estilizadas dinamicamente por nível:
     - **Alta ($\ge 75\%$)**: Preenchimento verde (`.conf-alta`).
     - **Média ($\ge 50\%$)**: Preenchimento amarelo/âmbar (`.conf-media`).
     - **Baixa ($< 50\%$)**: Preenchimento vermelho (`.conf-baixa`).
   - **Diálogo Seguro de Exclusão**: Diálogo modal `#permissao-apagar` com confirmação expressa antes de efetivar o `DELETE` no servidor, exibindo avisos visuais de status (sucesso/erro) de 2,5s.

### Sprite de Ícones Vetoriais SVG

O arquivo [`assets/icones.svg`](file:///d:/VSCode/Repositorios%20GitHub/Lucas/Projeto-TCC/Projeto-TCC/assets/icones.svg) reúne uma biblioteca de **17 ícones vetoriais** leves e nativos, eliminando o consumo de fontes externas pesadas e garantindo operação 100% offline:

| Símbolo (`id`) | Aplicação no Sistema |
| :--- | :--- |
| `#escudo` | Ícone principal de segurança na Tela de Bloqueio e cabeçalho do Dashboard |
| `#camera` | Cabeçalho do monitoramento da câmera e selo nos cartões da Galeria |
| `#clipboard` | Cabeçalho do console de logs e KPI de Total de Observações |
| `#alerta` | KPI de Tipos de Infração e ícone de aviso no diálogo de exclusão |
| `#tendencia` | KPI de Infração Mais Comum |
| `#relogio` | KPI de Data/Hora da Última Ocorrência |
| `#grafico` | Cabeçalho do gráfico de conformidade e seção de detalhes do modal |
| `#tabela` | Cabeçalho da tabela de eventos recentes |
| `#mouse` | Guia de instrução para demarcação da área de risco no canvas |
| `#limpar` | Ação de limpar logs, limpar área de risco e excluir ocorrência |
| `#cadeado` | Botão para bloqueio manual da interface |
| `#imagem` | Botão de acesso ao Dashboard, cabeçalho da galeria e botão Ver Fotos |
| `#atualizar` | Botões de recarregar dados do Dashboard e da Galeria |
| `#voltar` | Botões de retorno da Galeria para o Dashboard e do Dashboard para a Câmera |
| `#fechar` | Botão de fechar o modal de detalhes e cancelar a exclusão |
| `#confere` | Indicador visual de sucesso ao apagar registro da galeria |
| `#x` | Indicador visual de falha na exclusão de registro |

---

## 📡 Protocolos de Comunicação e APIs

### Rotas HTTP REST (FastAPI)

Disponibilizadas pelo módulo `banco.py` e expostas pelo `servidor.py`:

| Método | Rota | Parâmetros | Tipo Retorno | Descrição |
| :---: | :--- | :--- | :---: | :--- |
| `GET` | `/foto/{nome_foto}` | `nome_foto` (path) | `image/jpeg` | Retorna o arquivo de imagem do pendrive via `FileResponse`. Protegido contra path traversal via `os.path.basename`. |
| `GET` | `/listar_ocorrencias` | N/A | `application/json` | Retorna a lista completa de ocorrências registradas no SQLite, ordenadas por `id DESC`. |
| `GET` | `/dashboard_dados` | N/A | `application/json` | Retorna o compilado com total de eventos, distribuição quantitativa, taxas percentuais e eventos recentes. |
| `DELETE` | `/excluir_ocorrencias` | `imagem_deletar` (query),<br>`id` (query) | `application/json` | Exclui o arquivo JPEG correspondente em `/app/pendrive/evidencias/` e remove a linha do banco SQLite. |

#### Exemplo de Resposta: `GET /dashboard_dados`
```json
{
  "total_observacoes": 4,
  "resumo_conformidade": {
    "Sem capacete": 2,
    "Sem colete": 1,
    "Seguro, todos os EPIs detectados": 1
  },
  "taxa_conformidade": {
    "Sem capacete": 50.0,
    "Sem colete": 25.0,
    "Seguro, todos os EPIs detectados": 25.0
  },
  "eventos_recentes": [
    {
      "id": 4,
      "timestamp": "2026-11-01T10:14:22",
      "tipo_infracao": "Sem capacete",
      "caixa_operario": "[120, 85, 310, 420]",
      "posicao_x": 215.0,
      "posicao_y": 252.5,
      "conf_pessoa": 0.92,
      "conf_capacete": null,
      "conf_colete": 0.88,
      "caminho_foto": "foto_1793530462_Sem capacete_[120, 85, 310, 420].jpg"
    }
  ]
}
```

---

### Mensageria WebSocket (`WebUI`)

Comunicação bidirecional contínua baseada em Socket.IO gerenciada pelo `servidor.py`:

| Evento | Direção | Payload | Descrição |
| :--- | :---: | :--- | :--- |
| `senha` | Cliente ➔ Servidor | `{"senha": "<string>"}` | Submete a senha inserida na tela de bloqueio para validação. |
| `liberado` | Servidor ➔ Cliente | `{}` | Enviado com `room=cliente` para autorizar a navegação para a tela da câmera. |
| `rejeitado` | Servidor ➔ Cliente | `{}` | Enviado com `room=cliente` indicando senha inválida e ativando o alerta de erro. |
| `area_marcada` | Cliente ➔ Servidor | `{"x1": N, "y1": N, "x2": N, "y2": N}` | Define e ativa as novas coordenadas do retângulo de área de risco. |
| `limpar_box_risco` | Cliente ➔ Servidor | `{}` | Desativa e apaga a área de risco no backend (`box_risco = None`, `risco = False`). |
| `retornar_box_risco` | Cliente ➔ Servidor | `{}` | Solicita as coordenadas atuais da área de risco salva no backend. |
| `box_risco` | Servidor ➔ Cliente | `[x1, y1, x2, y2]` ou `null` | Retorna as coordenadas ativas da área de risco para sincronização visual do canvas. |
| `log_deteccao` | Servidor ➔ Cliente | `<string de texto>` | Transmite mensagens de telemetria e avisos operacionais em tempo real. |

---

### Padronização dos Logs do Sistema

As mensagens transmitidas pelo backend via `servidor.enviar_log()` seguem um padrão visual de prefixos categorizados:

- `[OK]: Operario com todos os EPIs e seguro!`
- `[ALERTA]: Operario na posição (...) identificado sem colete!`
- `[ALERTA]: Operario na posição (...) identificado sem capacete!`
- `[ALERTA]: Operario na posição (...) está em área de risco!`
- `[SUCESSO]: Pendrive montado e pronto`
- `[ERRO]: Pendrive não encontrado`
- `[BANCO]: Tabela de ocorrências pronta!`
- `[SUCESSO]: Imagem salva!`
- `[ERRO]: Falha no banco de dados | detalhes do erro: <mensagem>`
- `[AVISO]: Não existe registros nesse caminho!`

---

## 🚀 Guia de Configuração e Execução

### Pré-requisitos

1. Placa **Arduino UNO Q** conectada via porta USB ao computador de desenvolvimento.
2. Software **Arduino App Lab** instalado e configurado com suporte aos bricks da plataforma.
3. Câmera USB compatível conectada à placa e mapeada como dispositivo de vídeo `/dev/video0` (índice `0`).
4. Pendrive USB formatado (FAT32 ou ext4) conectado à placa e montado no diretório do contêiner em `/app/pendrive`.

### Configuração de Credenciais

Por questões de segurança, o arquivo `python/config.py` não é versionado pelo Git (incluso no `.gitignore`). Para configurar a senha de acesso:

1. Acesse o diretório `python/`.
2. Duplique o arquivo de exemplo `config.example.py` renomeando-o para `config.py`:
   ```bash
   cp python/config.example.py python/config.py
   ```
3. Abra o arquivo `python/config.py` e defina sua senha de preferência:
   ```python
   SENHA_SALVA = "sua_senha_secreta_aqui"
   ```

### Executando no Arduino App Lab

1. Abra o **Arduino App Lab**.
2. Conecte sua placa Arduino UNO Q e confirme a conexão com a placa.
3. Importe ou abra a pasta do projeto `Projeto-TCC`.
4. Certifique-se de que o ponto de montagem `/app/pendrive` esteja acessível na placa.
5. Clique em **Run** no Arduino App Lab. O ecossistema fará o download/carregamento do modelo neural `ei-model-1127250-2`, inicializará a câmera e subirá o servidor web.
6. Abra o navegador no endereço IP local informado pelo Arduino App Lab (geralmente `http://<ip-da-placa>:7000`).
7. Digite a senha configurada no `config.py` para desbloquear o painel.

---

### Ajustes e Calibração de Parâmetros

Os principais hiperparâmetros de visão computacional e persistência podem ser calibrados no arquivo [`python/detector.py`](file:///d:/VSCode/Repositorios%20GitHub/Lucas/Projeto-TCC/Projeto-TCC/python/detector.py):

| Parâmetro | Linha / Variável | Padrão | Descrição do Impacto |
| :--- | :--- | :---: | :--- |
| **Resolução de Captura** | `Camera(..., resolution=(720, 480))` | `(720, 480)` | Resolução nativa de entrada do pipeline. Pode ser reduzida para `(320, 320)` para aumentar o framerate. |
| **Taxa de Quadros (FPS)** | `Camera(..., fps=10)` | `10` | Frequência de leitura da câmera USB. |
| **Limiar de Confiança** | `confidence=0.5` | `0.5` | Confiança mínima exigida das inferências do modelo YOLO (ajustar entre $0.3$ e $0.7$ dependendo da iluminação). |
| **Distância de Tracking** | `DISTANCIA_MAXIMA = 90` | `90` px | Distância euclidiana máxima permitida entre centroides de frames consecutivos para associar a um mesmo ID. |
| **Timeout de Operário** | `rastrear_operarios` | `20` s | Tempo de tolerância para expurgo de operários que deixaram o campo de visão da câmera. |
| **Cooldown de Salvamento** | `rastrear_operarios` | `20` s | Intervalo mínimo obrigatório entre capturas fotográficas consecutivas para o mesmo operário rastreado. |

---

## 👥 Autoria e Créditos

Projeto desenvolvido como Trabalho de Conclusão de Curso (**TCC**) por:

- **Lucas Perine** ([GitHub](https://github.com/LucasPerine93))

**Foco da Pesquisa**: Aplicação prática de Inteligência Artificial, Edge Computing e Visão Computacional na mitigação de acidentes de trabalho e automação da fiscalização de conformidade em ambientes industriais de alto risco.
