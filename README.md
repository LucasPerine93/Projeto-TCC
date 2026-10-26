# Painel de Monitoramento de EPIs

## Objetivo

Sistema embarcado de monitoramento e detecção de Equipamentos de Proteção Individual (EPIs) — Capacete e Colete — em tempo real, utilizando visão computacional com YOLOv11n e placa Arduino UNO Q via Arduino App Lab.
## Hardware e Plataforma

- **Placa:** Arduino UNO Q (executa TODO o sistema embarcado via Arduino App Lab — inferência YOLOv11n, captura de vídeo, banco SQLite, interface web e tracking de operários)
- **Modelo de IA:** `ei-model-1127250-2` (Edge Impulse — YOLOv11n integrado ao firmware da placa)
- **Câmera:** Dispositivo USB/índice 0, resolução **720×480** a **10 FPS** (configurável em `detector.py`)
- **Armazenamento:** Pendrive montado em `/app/pendrive` — banco SQLite `seguranca.db` e evidências (fotos) na pasta `evidencias/`
## Estrutura de Arquivos (branch `main`)

```text
Projeto-TCC/
├─ app.yaml                     # Configuração do modelo Edge Impulse (ei-model-1127250-2)
├─ assets/                      # Frontend Web (HTML, CSS, JS, ícones)
│  ├─ index.html
│  ├─ styles.css (css/)
│  ├─ scripts/ (js/)
│  └─ libs/ (bibliotecas externas)
│  └─ README.md (documentação da UI)
├─ python/
│  ├─ main.py                   # Ponto de entrada — inicia App, detector, servidor, banco
│  ├─ detector.py               # YOLOv11n + tracking + verificação de zonas (ZONA_CAPACETE, ZONA_COLETE)
│  ├─ banco.py                  # SQLite — tabela ocorrencias, migração de esquema, dados do dashboard
│  └─ servidor.py               # FastAPI + WebUI — WebSockets, rotas HTTP (/login, /dashboard_dados, /foto, etc.)
└─ .git/                        # Controle de versão
```

> **Nota:** Pastas `tests/`, `docs/` e `tools/` **não fazem parte da branch `main`** e foram excluídas desta documentação.
## Como o Pipeline Funciona

1. **Inicialização (`main.py`)**

   - Cria o objeto `Camera(source=0, resolution=(720, 480), fps=10)`
   - Instancia `VideoObjectDetection` com o modelo Edge Impulse (`ei-model-1127250-2`)
   - Define `confidence=0.5` e `debounce_sec=0`
   - Inicia o loop principal: `App.run()`

2. **Captura e Detecção (`detector.py`)**

   - A câmera captura frames a 720×480, 10 FPS
   - A cada frame, o YOLOv11n executa inferência e retorna bounding boxes (em pixels) + confianças
   - **Todas as coordenadas das ZONAS são normalizadas** (valores entre 0.0 e 1.0 relativos à largura/altura da frame):
     - `ZONA_CAPACETE = (-0.15, 0.35)` — faixa vertical próxima ao topo da caixa da pessoa
     - `ZONA_COLETE = (0.36, 0.80)` — faixa vertical central/abdominal
   - As coordenadas já vêm normalizadas pelo modelo — mudar a resolução da câmera **não quebra** a lógica de zonas

3. **Verificação de EPIs e Área de Risco**

   - `verificar_epi(box_epi, box_operario, local_corpo)` — verifica se o EPI (capacete/colete) está na zona corporal correta (topo vs base da caixa da pessoa)
   - `verificar_area_risco(box_risco, box_pessoa)` — testa se o centro da pessoa está dentro da área de risco marcada pelo usuário na interface web
   - Os boxes vêm da deteção já na resolução atual do frame

4. **Filtro de Tempo de Espera (`TEMPO_ESPERA_SALVAR`)**

   - Definido em `seguranca.py` (constante em segundos)
   - Impede que múltiplas ocorrências do mesmo operário sejam salvas consecutivamente
   - O callback `operario_detectado` chama `organizar_dado`, que associa o operário, os EPIs e a área de risco, então valida o cooldown antes de persistir

5. **Salvamento no Banco de Dados (`banco.py`)**

   - Banco SQLite em `/app/pendrive/seguranca.db`
   - Tabela `ocorrencias` com colunas: `id, timestamp, tipo_infracao, posicao_x, posicao_y, conf_pessoa, conf_capacete, conf_colete, caminho_foto, caixas`
   - Migração leve e idempotente adiciona colunas `caixas, status, motivo, revisado_em` se o banco for antigo
   - Foto da cena é salva em `/app/pendrive/evidencias/` (caminho armazenado em `caminho_foto`)
   - Cada ocorrência recebe status `pendente` inicialmente; técnico pode revisar depois (status: `confirmada` ou `descartada`)

6. **Interface Web e Logs (`servidor.py`)**

   - FastAPI expõe WebSockets para logs de detecção em tempo real (`log_deteccao`)
   - Área de risco é marcada no canvas frontend → atualiza `box_risco` global, usado por `verificar_area_risco()`
   - Rotas HTTP: `/login`, `/sessao`, `/logout`, `/foto/{nome_foto}`, `/listar_ocorrencias`, `/dashboard_dados`, `/revisar_ocorrencia`, `/excluir_ocorrencia`
   - Dados de dashboard vêm de `banco.calcular_dados_dashboard(dias)` com conformidade, contagens por tipo/status, série diária, etc.
## Como Executar no Arduino App Lab

1. **Abrir o projeto**:

   - No Arduino App Lab, escolha 'Open from GitHub' ou 'Upload Files'
   - Navegue até a pasta `Projeto-TCC` dentro do repositório
   - Ou faça o upload dos arquivos `app.yaml`, `python/` e `assets/`

2. **Conectar a placa**

   - Conecte a placa Arduino UNO Q via USB ao computador
   - Certifique-se de que o pendrive está montado na pasta `/app/pendrive` (ou destino configurado)

3. **Executar**

   - Clique em 'Run' no App Lab
   - O sistema iniciará a captura de vídeo (720×480 @ 10 FPS), começará a detectar EPIs e abrirá a interface web
   - Logs aparecerão no console e na WebUI; ocorrências serão salvas no SQLite no pendrive

4. **Configurações opcionais (em `detector.py`)**

   - Alterar `resolution` para `(320, 320)` para aumentar FPS (as `ZONA_CAPACETE` e `ZONA_COLETE` continuam funcionando — são normalizadas)
   - Ajustar `confidence` (padrão 0.5) para mais ou menos detecções
   - Modificar `TEMPO_ESPERA_SALVAR` em `seguranca.py` se o intervalo de salvamento precisar mudar

5. **Acessar a interface web**

   - Após o início, a URL local será exibida (geralmente `http://localhost:8080` ou similar)
   - Use as rotas `/dashboard_dados` para ver estatísticas, `/listar_ocorrencias` para ver o banco, ou faça login (`/login`) para gestão de revisões
## Licença

Projeto de TCC — Instituto de Tecnologia. Desenvolvido por Lucas Perine e Victor Rodrigues.
