# PLANO DE EVOLUÇÃO — Painel de EPIs + Gêmeo Digital 3D

Base: branch `develop` (commit `7e66e95`), trabalho na branch local `feat/gemeo-3d-evolucao`.
Nada foi enviado ao GitHub e a `main` não foi tocada.

> **O que NÃO foi testado:** nada rodou no Arduino UNO Q nem com a câmera real. Os testes
> foram feitos em navegador headless (Chromium com renderização por software), com um servidor
> de testes e com stubs de `arduino.*`. Medidas de desempenho abaixo valem só como comparação
> relativa; repita no equipamento de uso (seção 10).

---

## 1. Arquitetura atual (verificada nos arquivos)

```
Câmera 720×480 → YOLO (VideoObjectDetection) → detector.organizar_dado
  → associar EPI→operário → risco (centro da caixa dentro do retângulo) → associar_trilhas (IoU+distância)
  → filtrar_salvamento (cooldown 20 s por trilha+tipo) → SQLite + .jpg    → amostragem (pessoa-frame/min)
  servidor.py (FastAPI + WebUI): rotas REST + sockets  →  assets/ (HTML/CSS/JS puro, ES modules)
```

* Frontend: `index.html`, `css/style.css`, `js/{app,nucleo,tela_*,grafico,util,api,tema,cenas,conexao_ui}.js`.
  O backend **só envia ao socket** a mensagem `log_deteccao` (texto) e `box_risco`. Não envia posição de
  trabalhadores, trilhas, confiança ao vivo nem estado dos EPIs em formato estruturado.
* Tamanho do frame: 720×480 (`detector.py`, `cenas.js`).

## 2. Resumo da auditoria

| Situação | Itens |
|---|---|
| **Implementado e funcionando** | Login (PBKDF2, cookie), Ao vivo (vídeo + área de risco + logs, limite de 300), Ocorrências (revisão sem apagar, CSV), Painel (conformidade, gráfico SVG, rosca), trilhas efêmeras, amostragem pessoa-frame, tema claro/escuro. |
| **Parcial** | Tratamento de queda do socket (só o chip "Conectado/Sem conexão"); câmera embutida por `iframe :4912` (sem reconexão automática do vídeo além do teste a cada 8 s). `conexao_ui.js` depende do global `WebUI` de `libs/arduino.js`. |
| **Só simulação** | Todo o Gêmeo 3D (operários, rotas BFS, infrações, câmeras PTZ, ArUco, ponto cego, confianças do CCTV). Ele **não existia na `develop`**; foi portado do protótipo v7 nesta etapa. |
| **Preparado para dados reais** | Adaptador `fonte_dados.js` (novo) e o canal `telemetria_gemeo` no socket do painel (o backend ainda não envia). |
| **Não existe** | Posição na planta; calibração câmera→planta sobre a imagem **real**; mapa de calor com dados reais; histórico de trajetória; assistente de IA; testes automatizados do frontend (agora há de adaptador); `config.py` (citado em `docs/arquitetura.md`, ausente). |

## 3. Opinião técnica (respostas às 10 perguntas)

1. **Maior problema arquitetural:** o backend não expõe o estado estruturado da cena. Tudo que a UI sabe vem de logs em texto (`"[ALERTA]: Operario na posição [x1,y1,x2,y2] ..."`) ou de fotos gravadas. Sem um quadro estruturado (trilha, caixa, EPIs, risco) o gêmeo não pode refletir a realidade.
2. **O gêmeo estava pronto para dados reais?** Não. Tinha só 2 avatares fixos (`OP-01/OP-02`), caía **silenciosamente para a simulação** quando o WebSocket caía, mostrava confianças inventadas (senoides) no CCTV, ArUco e "ponto cego" simulados, e contabilizava conformidade simulada como se fosse métrica. Corrigido (seção 5).
3. **Remover/simplificar:** a identificação por ArUco e o ponto cego **simulados** são conceitos do protótipo, não do sistema real (que não identifica pessoas). Agora só existem no modo simulação. Considere esconder os dois em uma versão de demonstração final.
4. **Decisões que podem prejudicar o desempenho:** o motor redesenhava o mapa de sombras (2048²) **a cada quadro** sem necessidade, rodava sem teto de quadros e criava geometrias por operário. Corrigido. No lado da placa: enviar telemetria a mais de ~10 Hz ou com imagens embutidas aumentaria carga no UNO Q; o renderizador 3D roda no navegador do usuário, não na placa.
5. **Melhor ligação detecção→3D:** o backend envia, a ~5 Hz, um quadro estruturado com `track_id`, caixa, EPIs, confiança e risco (seção 6); o **frontend** converte caixa→planta aplicando a homografia calibrada. Assim a placa não faz geometria extra e a calibração pode mudar sem reiniciar o backend.
6. **O que diferencia o TCC:** (a) o gêmeo alimentado por dados reais com origem sempre explícita; (b) a **taxa de conformidade por pessoa-frame** com denominador honesto (já existe); (c) validação experimental com protocolo (seção 12); (d) mapa de calor normalizado por exposição (seção 8).
7. **Interessante mas não vale o custo agora:** reconstrução 3D de poses, modelos glTF detalhados, assistente de IA local no UNO Q, "replay" com vídeo. Faça replay de **trajetória**, não de vídeo.
8. **Ferramentas:** Chrome DevTools (Performance/Memory) para medir; Blender só se quiser modelos `.glb` low-poly; **não** adicione OpenCV ao navegador (a homografia 3×3 já está em JS, ~30 linhas). Para rastreamento mais robusto, avalie uma implementação enxuta de ByteTrack/IoU em Python no backend, só depois de medir a troca de IDs.
9. **O que eu mudaria na proposta:** não prometa "sincronização em tempo real" antes de medir latência e erro de posição; prometa um **limite medido** ("erro médio X m, atraso Y ms em Z condições"). E trate a posição como estimativa (ver seção 7).
10. **Três prioridades:** (1) emitir `telemetria_gemeo` no backend; (2) calibração sobre um **frame real** da câmera + medidas físicas; (3) protocolo de validação com dados anotados.

## 4. Problemas encontrados na `develop` (fora do gêmeo)

**Corrigidos (pequenos e seguros):**
* `tests/conftest.py`: o stub de `fastapi` não tinha `Request`/`JSONResponse`, então os testes falhavam onde a lib não existe.
* `tests/test_painel.py`: importava `test_pipeline` por caminho que só funciona se o diretório `tests` estiver no `sys.path`; falhava em `pytest` a partir da raiz.
* `css/style.css`: comentários com texto corrompido (`â€”`, `Ã­`); só comentários, nenhum efeito visual.

**Observações sobre a lógica de detecção (NÃO alteradas; exigem decisão e teste com dados reais):**
* `verificar_area_risco` usa o **centro da caixa**. Para uma zona no **chão**, o correto é o ponto de contato (centro da base da caixa). Com a câmera inclinada, o centro do tronco pode cair dentro da zona com os pés fora (ou o contrário). Impacto: falsos positivos/negativos de invasão. Correção sugerida: usar `((x1+x2)/2, y2)`; medir antes/depois no experimento.
* `associar_trilhas` decide **trabalhador por trabalhador, em ordem de lista**, não por atribuição global. Num cruzamento, a ordem da lista pode trocar IDs; e a regra de ambiguidade cria **trilha nova**, o que gera ocorrência repetida (o cooldown é por trilha). Sugestão: atribuição global (húngaro/guloso por placar) e medir trocas de ID.
* `TEMPO_VIDA_TRILHA = 20 s` (igual ao cooldown): uma trilha antiga pode "adotar" outra pessoa que apareça perto da última posição. Considere TTL menor para associação, mantendo 20 s só para o cooldown de ocorrência.
* `analisar_seguranca` usa um cooldown **global** de 5 s só para logs: quem surge ou muda de estado dentro da janela só aparece no log na rodada seguinte (o banco não é afetado).
* `docs/arquitetura.md` cita `config.py`, inexistente.

## 5. Alterações realizadas nesta etapa

Arquivos novos: `assets/css/gemeo.css`, `assets/js/tela_gemeo.js`, `assets/js/assistente.js`, `assets/js/gemeo/{fonte_dados,motor,interface}.js`, `assets/libs/three.min.js` (r128, local), `tools/ws_teste_gemeo.py`, `tests/js/test_fonte_dados.js`, este plano.
Alterados: `assets/index.html` (4ª aba, painel de fonte, assistente), `assets/js/{app,nucleo}.js`, `assets/icones.svg` (+10 ícones), `assets/css/style.css` (seção do assistente + comentários), `docs/arquitetura.md`, `tests/conftest.py`, `tests/test_painel.py`. **Nenhum arquivo Python do backend foi alterado.**

**Gêmeo 3D**
* **Origem dos dados sempre visível:** selo `SIMULAÇÃO` (âmbar) / `DADOS REAIS` (verde) / `SEM DADOS REAIS` (vermelho), faixa dentro do 3D ("SIMULAÇÃO · dados fictícios") visível também no celular, e KPI "Conformidade … simulada/real". O monitor CCTV agora diz **"VISTA VIRTUAL"** (antes dizia `REC` e `YOLOv11n · ei-model…`, que sugeriam câmera real).
* **Sem dados reais, sem avatares:** ao escolher a fonte real, a simulação é desligada e a cena fica vazia até chegarem quadros. Se o sinal some por mais de 3 s ou o canal cai, os avatares são removidos (nenhuma posição "congelada" é mostrada como atual). Não há mais retorno automático à simulação.
* **Zera ao trocar de fonte:** conformidade, mapa de calor, replay e contagem de invasões (dados simulados não contaminam os reais, e vice-versa).
* **Adaptador `fonte_dados.js`:** aceita 3 formatos (proposto, plano v7, nativo do detector), valida, limita a 32 trabalhadores, descarta quadros repetidos/fora de ordem, entrega só o quadro mais recente por frame de tela (várias mensagens → uma atualização), reconecta com espera crescente, mede taxa e atraso.
* **Pool de 6 avatares** alocados por `id` de trilha real (antes: 2 fixos). Excedentes geram aviso. Rótulos reaproveitam a textura.
* **Trilha sem posição:** se chegar só a caixa da imagem, a pessoa é contada, mas **não é desenhada** até existir calibração (não se inventa posição).
* **PPE desconhecido:** mostrado como `?` e **não** gera infração.
* No modo real, o CCTV mostra apenas confianças enviadas pelo detector (antes eram valores gerados por seno), e ArUco/ponto cego simulados ficam desligados.

**Desempenho (Three.js)**
* Mapa de sombras só é refeito quando a estrutura muda ou durante a extrusão (só paredes/pilares projetam sombra; antes era todo quadro).
* Teto de 30 quadros/s com cena em movimento e 6 quadros/s quando parada; pausa total com a aba oculta ou o documento em segundo plano (já existia).
* `devicePixelRatio` limitado a 1,5 (era 2).
* Geometrias e materiais comuns dos operários compartilhados; monitor CCTV minimizado não faz o segundo desenho.
* `window.GemeoPerf.snapshot()` no console devolve fps, ms/quadro, chamadas de desenho, triângulos, geometrias e texturas.
* **Medida (headless, renderização por software, 4 execuções alternadas):** ~105–112 ms/quadro antes → ~85 ms/quadro depois, redução de cerca de **20–24 %** no custo por quadro, só pela correção das sombras. O efeito do teto de 30 fps e do DPR não aparece nesse ambiente (limitado por CPU); meça no dispositivo real.

**Interface e confiabilidade**
* Painel "Fonte dos dados" com dois caminhos: conexão do painel (Arduino) e WebSocket externo (avançado). Ao sair da sessão, a fonte real é fechada.
* **Assistente de IA (estrutura):** botão no topo → painel lateral retrátil, acessível por teclado (Esc fecha, foco volta ao botão), empurra o conteúdo em telas ≥1100 px (não cobre câmera nem 3D) e sobrepõe em telas menores. Marcado **"Não conectado"**; campo e botão desativados; nenhuma resposta simulada.
* Abas do gêmeo usam os tokens e componentes do site (claro/escuro); palco 3D e CCTV ficam escuros fixos.

## 6. Integração futura com dados reais

### 6.1 Mensagem recomendada (backend → socket do painel)

Nome da mensagem: `telemetria_gemeo`. Um quadro por mensagem, **contínuo a 2–10 Hz** (inclusive `workers: []` quando ninguém está na cena; o gêmeo considera "sem sinal" após 3 s calados).

```json
{
  "source": "real",
  "timestamp": 1760000000000,        // ms desde 1970 (relógio da placa)
  "sequence": 1234,                  // cresce a cada quadro
  "frame": { "w": 720, "h": 480 },
  "workers": [{
    "id": "7",                       // track_id efêmero (sem identidade civil)
    "bbox": [x1, y1, x2, y2],        // pixels do frame (hoje já existe em Operario.box_xyxy)
    "ppe": { "helmet": true, "vest": false },
    "confidence": { "person": 0.96, "helmet": 0.91, "vest": null },
    "inRisk": false
  }]
}
```
`position {x,z}` (metros) é **opcional**: se vier, o gêmeo usa; se vier só `bbox`, o gêmeo calcula o ponto do chão `(centro_x, y2)` e aplica a homografia calibrada (quando existir; ver seção 7). O adaptador também entende o formato plano da v7 e o nativo do `Operario` (`track_id, box_xyxy, tem_capacete, tem_colete, conf_*, risco_detectado`).

### 6.2 O que falta no backend (NÃO implementado de propósito)

Não foi alterado o Python (não há como testar no UNO Q aqui). Trecho sugerido, para aplicar e medir:

```python
# servidor.py
import time
_seq = 0
def enviar_telemetria(operarios):
    global _seq
    _seq += 1
    ui.send_message("telemetria_gemeo", {
        "source": "real", "timestamp": int(time.time() * 1000), "sequence": _seq,
        "frame": {"w": 720, "h": 480},
        "workers": [{
            "id": str(o.track_id), "bbox": list(o.box_xyxy),
            "ppe": {"helmet": o.tem_capacete, "vest": o.tem_colete},
            "confidence": {"person": o.conf_pessoa, "helmet": o.conf_capacete, "vest": o.conf_colete},
            "inRisk": bool(o.risco_detectado)} for o in operarios if o.track_id is not None]})
```
Chamar no fim de `detector.organizar_dado` (depois de `filtrar_salvamento`, que atribui os `track_id`), **com limite de ~5 Hz** (`if agora - ultimo_envio < 0.2: return`) e dentro de `_executar_seguro`. Sem imagens no payload. Observação: o fluxo existente trata `lista_operarios == []` retornando cedo em `organizar_dado`; para enviar quadros vazios é preciso chamar a função também nesse caso.

### 6.3 Ordem para ligar
1. Aplicar o trecho acima e checar no navegador: o selo muda para `DADOS REAIS`.
2. Verificar taxa (`GemeoPerf`, status do painel de fonte mostra quadros/s e atraso) e CPU da placa.
3. Só então calibrar (seção 7).

## 7. Calibração câmera → planta

* **O que já existe:** calibrador de 4 pontos no gêmeo (resolve o sistema 8×8 em JS, erro de reprojeção ~1e-12 px em teste) por câmera. **Limite atual:** ele é feito sobre a *câmera virtual* do gêmeo (640×480), não sobre o frame real (720×480); portanto **não serve ainda** para converter detecções reais.
* **O que falta:** (a) mostrar um *frame real congelado* da câmera (o fluxo é um `iframe` em `:4912`; é preciso um endpoint `/snapshot` ou capturar do `<video>` se o iframe permitir); (b) o usuário clica 4+ pontos conhecidos do piso e informa as **medidas reais** (m); (c) guardar `H` e o tamanho do frame (`localStorage` ou, melhor, rota do backend para sobreviver à troca de navegador); (d) recalibrar sempre que a câmera for mexida (mostrar validade/data); (e) aplicar `H` ao ponto `(centro_x, y2)` da caixa.
* **Uma câmera consegue:** posição no **plano do piso**, assumindo que o ponto de contato (pés) é visível. **Não consegue:** altura/pose, posição de quem está sobre degrau/plataforma (fora do plano), nem pessoas cujos pés estão ocultos (a caixa corta no tronco → erro grande ao longe). O erro cresce com a distância e com o ângulo de visada; **meça** com pontos marcados no piso (seção 12) e informe o erro, não a precisão nominal.
* Não é reconstrução 3D do corpo.

## 8. Gêmeo sincronizado, mapa de calor e exposição

* **Sincronização:** fluxo da seção 6; o gêmeo só aplica o último quadro por tela (nada fica em fila). Latência = relógio da placa vs. do navegador; compare `timestamp` com `Date.now()` apenas se os relógios forem sincronizados (NTP), caso contrário use o atraso relativo entre quadros.
* **Mapa de calor:** hoje é alimentado pelas posições do gêmeo (`heatGrid`) e zera ao trocar de fonte. Para ser válido com dados reais: acumular **tempo de exposição por célula** (`s` com pessoas) e **eventos por célula**; mostrar `eventos ÷ exposição` (taxa por hora-pessoa), não só contagem, pois áreas movimentadas acumulam mais eventos só por receber mais gente. Filtros por tipo de evento e por período vêm do `/listar_ocorrencias` (precisa incluir posição na planta ao gravar).
* **Tempo de exposição:** por trilha, `entrada = primeiro quadro em risco`, `saída = último quadro em risco + tolerância (ex.: 1,5 s)`; lacunas (queda de sinal ou perda de trilha) devem ser **marcadas como "sem dados"**, nunca contadas como "fora de risco" ou "dentro". Reporte como estimativa com faixa ("≈ 42 s, de 38 a 51 s").

## 9. Histórico e reprodução em 3D

Estrutura sugerida (tabela `trajetoria`): `ocorrencia_id, track_id, t_ms, x_m, z_m, helmet, vest, in_risk, fonte`. Amostrar **1–2 Hz** (não 10 Hz), e guardar só uma janela de ±15 s ao redor de cada ocorrência (≈ 30–60 linhas × ~40 bytes ≈ 1–3 KB por ocorrência), com retenção (ex.: 90 dias) e `VACUUM` periódico. Reconstrução aproximada = interpolação linear entre amostras (o replay atual do gêmeo já interpola). Hoje o replay existe só para trajetórias **simuladas** (ring de 30 pontos a 5 Hz); ele só deve ser oferecido para dados reais depois que a tabela existir.

## 10. Medição de desempenho (metodologia antes/depois)

1. Chrome DevTools → **Performance**: gravar 30 s na aba Gêmeo 3D com a mesma planta, sem interação. Registrar: FPS médio, tempo de *Scripting* e de *GPU*, e frames longos (> 50 ms).
2. **Memory**: três snapshots (aba aberta, 10 min depois, após sair e entrar); crescimento contínuo de `Geometry/Texture` indica vazamento. `GemeoPerf.snapshot()` já lista geometrias/texturas.
3. Comparar `main` do protótipo (v7) × esta branch no **mesmo dispositivo**; repetir ≥ 5 vezes e usar a mediana.
4. No UNO Q: medir CPU/RAM da placa com e sem a aba aberta e com a telemetria ligada (o 3D roda no navegador do cliente; a placa só envia dados).

## 11. Assistente de IA

* **Agora:** só a estrutura visual (`assistente.js`, `#painel-ia`). Sem rede, sem modelo, sem texto gerado.
* **Arquitetura futura:** UI continua em HTML/JS; as perguntas vão a uma rota nova do backend (ex.: `POST /assistente`) que só consulta o SQLite (acesso **somente leitura**, via funções já existentes em `banco.py`) e chama um modelo em **outro equipamento da rede local** (o UNO Q não tem recursos) ou um serviço externo **somente com ação explícita** do usuário. Sem imagens e sem dados pessoais no prompt por padrão. Sem ferramentas de escrita (não altera área de risco, regras ou equipamentos). Registrar cada pergunta e resposta (auditoria).
* **Pontos de integração:** `/dashboard_dados` e `/listar_ocorrencias` para contexto; um comando visual (ex.: "mostrar região no gêmeo") deve ser uma ação **sugerida** que o usuário aprova.

## 12. Validação experimental (o que medir; sem metas inventadas)

| Aspecto | Como medir | Dados a coletar |
|---|---|---|
| Precisão/revocação de EPIs | ≥ 300 imagens anotadas (com/sem capacete e colete, vários horários) | TP/FP/FN por classe, matriz de confusão, IC 95 % |
| Associação EPI→pessoa | frames com 2+ pessoas próximas | % de EPIs ligados à pessoa errada |
| Estabilidade de ID | vídeos com cruzamentos | nº de trocas de ID por minuto, fragmentação de trilha |
| Erro de posição no 3D | pontos marcados no piso com fita métrica | erro em metros (média, p95) por faixa de distância |
| Latência | `timestamp` do backend × tela, relógios sincronizados | mediana e p95 em ms |
| FPS e memória | seção 10 e `GemeoPerf` | séries temporais |
| Estabilidade prolongada | 4–8 h ligado | crescimento de memória, reinícios, quadros perdidos |
| Falha de conexão | desligar/religar rede e processo | tempo até `SEM DADOS REAIS`, tempo de recuperação |

Apresentação no TCC: tabelas com média ± desvio e n, gráficos de latência (caixa) e erro por distância, descrição do ambiente, e **limitações** (câmera única, iluminação, perspectiva).

## 13. Dependências e limitações
* Backend precisa emitir `telemetria_gemeo` (não existe).
* Posição real precisa de calibração sobre frame real (não existe).
* Pool de 6 avatares (excedentes não aparecem).
* `libs/three.min.js` é r128 (antiga, mas estável e local). Atualizar exige reteste.
* Conformidade do gêmeo só acumula com a aba visível (render pausado quando oculto).
* Não testado no UNO Q nem com a câmera real.
* O CSS do gêmeo usa tokens do site; a aba 3D não é adequada a telas < 360 px.

## 14. Ordem recomendada de implementação
1. `telemetria_gemeo` no backend (seção 6.2) + teste de carga na placa. *Depende de:* nada.
2. Snapshot do frame real + calibrador sobre o frame real. *Depende de:* 1 (para validar) e de medidas físicas do local.
3. Registrar posição na planta ao salvar ocorrência. *Depende de:* 2.
4. Tabela de trajetória + replay real. *Depende de:* 2 e 3.
5. Mapa de calor por exposição e tempo de exposição. *Depende de:* 2, 3 e das lacunas "sem dados".
6. Revisar `verificar_area_risco` (ponto do chão) e `associar_trilhas` (atribuição global) com dados anotados. *Depende de:* conjunto de teste (seção 12).
7. Protocolo de validação e coleta. Em paralelo com 2–6.
8. Assistente de IA conectado (somente leitura). *Depende de:* 3 e 5 para respostas úteis.

## 15. Como testar o que foi feito
* Unitários: `python3 -m pytest -q` (30) e `node tests/js/test_fonte_dados.js` (10).
* Modo real sem hardware: `python3 tools/ws_teste_gemeo.py` e, na aba Gêmeo 3D → botão de fonte → "Avançado" → `ws://localhost:8000/ws`.
* A aba só funciona com o **site inteiro** servido pelo App Lab (ela usa `libs/three.min.js` local; sem internet).
