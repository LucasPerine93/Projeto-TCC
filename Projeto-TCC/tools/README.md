# tools/ — scripts auxiliares (não sobem para a placa)

Esta pasta guarda utilidades de desenvolvimento. O servidor de preview
**não é versionado**: ele mora em `C:\Users\Usuario\Desktop\TCC\_preview_tcc\preview_server.py`
(e fora do Git de propósito, pois semeia banco fake + injeta hash de teste).

## Gêmeo 3D — lançador de demonstração de 1 clique (`iniciar_demo.py`)

Dois cliques em **`Iniciar_Demo_TCC.bat`** (raiz do projeto, um nível acima de `tools/`)
abrem o painel completo no navegador — login, ocorrências, revisão, URLs, Gêmeo 3D,
assistente IA, tela "Ao vivo" — sem terminal e sem digitar comando.

O que ele faz, nesta ordem:

1. **Garante um banco SQLite de demonstração** em `tools/.demo/` (ignorado pelo Git
   pela regra `*.db`; nada toca o pendrive real `/app/pendrive`). Semeadura só se o
   banco estiver vazio; re-execuções **não duplicam dados**:
   - 6 ocorrências variadas (Sem capacete, Sem colete, Sem capacete e colete,
     Invasão de área de risco; pendentes/confirmada/descartada) com
     `(x_m, z_m, celula_idx)` na planta e caixas de detecção coerentes com a
     infração (sem EPI faltante na lista, dois operários na cena de uma delas);
   - trajetórias de **±15 s** em `trajetoria` para o **Replay 3D** de toda ocorrência;
   - mapa de calor semeado em `exposicao_celula` (553+ células);
   - 7 dias × 4 janelas/min de amostras Pessoa-Frame em `amostras_minuto`
     (o Dashboard mostra conformidade real);
   - evidências JPEG 720×480 geradas em `tools/.demo/evidencias/`.
2. **`ws_teste_gemeo.py`** como subprocesso em `ws://localhost:8000/ws` (fonte
   "dados reais do WebSocket" no Gêmeo 3D, com 3 operários simulados).
3. **O painel real** (`python/servidor.py`, FastAPI + socket.io) em
   `http://127.0.0.1:8765`, com uma **câmera simulada** em
   `http://127.0.0.1:4912/embed` (a tela "Ao vivo" não fica quebrada sem a placa).
4. **Abre o navegador** e imprime no console o painel de acesso
   (`admin` / `admin123`, URLs, banco de dados e checklist do que testar).

Para encerrar: **Ctrl+C** na janela (servidor, WebSocket e câmera simulada são
encerrados; a calibração de demonstração só é removida se o próprio lançador a criou).

Opções: `--sem-navegador` (não abre o navegador) e `--verificar` (auto-verifica as
rotas principais — `/sessao`, `/listar_ocorrencias`, `/dashboard_dados`, `/mapa_calor`,
`/snapshot` — e encerra de forma limpa; útil em CI).

Dependência nova de desenvolvimento: **`python-socketio`** (5.x + engine.io; é o mesmo
protocolo que o navegador fala via `socket.io` 4.x — EIO=4). O `servidor.py` só é
alterado no lançador por stubs (o módulo `arduino.app_bricks.web_ui` e a importação
circular `servidor` ↔ `banco` exigem um adaptador; nada do comportamento do painel
muda). Atalho da Área de Trabalho: cópia de `Iniciar_Demo_TCC.bat` em
`C:\Users\Usuario\Desktop\TCC\Iniciar_Demo_TCC.bat` apontando para a pasta do
repositório.

## Preview local do painel (Windows)

```powershell
cd C:\Users\Usuario\Desktop\TCC\_preview_tcc
python preview_server.py
# abre http://localhost:8017/  (senha de teste: admin123)
```

O preview:
- aponta `PYTHON_DIR` para `Projeto-TCC/python` e `ASSETS` para
  `Projeto-TCC/assets` (verificado: caminhos continuam corretos);
- importa as funções REAIS de `banco.py`/`seguranca.py` (com stubs só para
  `arduino.*`/`fastapi`, ausentes no Windows);
- faz monkey-patch de `banco.CAMINHO_BANCO`/`banco.PASTA_FOTOS` para um
  SQLite temporário em `_preview_tcc/` — os aliases mantidos no `banco.py`
  (`CAMINHO_BANCO = config.CAMINHO_BANCO`) garantem que isso continua
  funcionando após a criação de `python/config.py`;
- serve os assets REAIS nos mesmos endpoints do UNO Q (`/`, `/app.js`,
  `/dashboard_dados`, `/listar_ocorrencias`, `/foto/{nome}`).

## Protocolo de validação experimental (`avaliar_experimento.py`)

Script da **Seção 12** do `PLANO_EVOLUCAO.md`: gera as métricas e tabelas que
entram na monografia (**Seção 14, Etapa 7**). Sem dependências externas
(apenas biblioteca padrão Python ≥ 3.8) e sem importar nada de `python/`
(o detector só é importado sob demanda se `--input` trouxer uma
`calibracao` com `box_xyxy`).

```powershell
# 1) Ver o formato das tabelas (dados SINTÉTICOS, não citáveis):
python Projeto-TCC\tools\avaliar_experimento.py --demo

# 2) Gravar o relatório exemplo em disco:
python Projeto-TCC\tools\avaliar_experimento.py --demo --output relatorio_validacao.md

# 3) Relatório final com a coleta real:
python Projeto-TCC\tools\avaliar_experimento.py --input dados_experimento.json --output relatorio_validacao.md
```

Funções (importáveis nos testes): `calcular_metricas_epi` (precisão,
revocação, F1, acurácia e **IC 95 % de Wilson** por classe + agregado micro),
`avaliar_erro_posicao` (erro euclidiano em m: média, DP, mediana, p95, máximo
e faixas `< 5m` / `5–10m` / `> 10m`), `avaliar_estabilidade_trilhas`
(ID switches/min, fragmentação, % associação EPI→pessoa), `avaliar_desempenho`
(mediana/média±DP/p95 de latência, FPS médio, ms/quadro e Δ de
geometrias/texturas dos `GemeoPerf.snapshot()`), e `gerar_relatorio_markdown`.

O cabeçalho do relatório declara explicitamente a **origem dos dados**:
`--demo` produz um bloco de aviso "DADOS SINTÉTICOS — NÃO CITAR NA
MONOGRAFIA"; `--input coleta.json` produz "Origem dos dados: arquivo real …".
Seções ausentes no JSON viram "Sem dados — colete na Seção 12" — o script
nunca inventa números. Decimais no padrão pt-BR.

O esquema do `dados_experimento.json` está documentado no cabeçalho do
módulo (`python Projeto-TCC\tools\avaliar_experimento.py --help` também ajuda).
Cobertura mínima: 300 imagens anotadas por classe, 12 medições com fita
métrica (≥ 4 por faixa de distância), ≥ 10 min de gravação com 2+ pessoas e
os snapshots de `GemeoPerf` do painel.

