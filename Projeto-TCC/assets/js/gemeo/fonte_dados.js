/* Camada de adaptação de dados do Gêmeo 3D.
 *
 * O motor 3D NÃO sabe de onde vêm os dados: ele só consome "quadros" normalizados.
 * Esta camada recebe mensagens brutas de qualquer origem (WebSocket externo, o socket do
 * painel Arduino, testes), valida, converte para um formato único e controla o estado
 * da conexão. A simulação não passa por aqui: ela é a fonte "simulation" do próprio motor.
 *
 * Quadro normalizado:
 *   { source: "real", timestamp: ms|null, sequence: n|null, receivedAt: ms,
 *     workers: [{
 *       id: "12",                          // identificador temporário da trilha (não é identidade civil)
 *       position: { x, z } | null,         // metros na planta (origem no centro); null = sem calibração
 *       direction: rad | null,
 *       ppe: { helmet: bool|null, vest: bool|null },   // null = não informado
 *       confidence: { person, helmet, vest },          // 0..1 ou null
 *       riskZoneIds: [], inRisk: bool|null,
 *       status: "safe" | "violation" | "risk" | "unknown",
 *       image: { bbox: [x1,y1,x2,y2], foot: [u,v] } | null   // pixels do frame da câmera
 *     }] }
 *
 * Formatos de entrada aceitos (todos viram o quadro acima):
 *   1. o formato proposto (workers[].position/ppe/confidence);
 *   2. o formato plano da v7:  { id, x, z, capacete, colete, inRisk };
 *   3. o formato nativo do detector Python (Operario): { track_id, box_xyxy, tem_capacete,
 *      tem_colete, conf_*, risco_detectado } — sem posição na planta (ver PLANO_EVOLUCAO.md).
 */
(function (raiz) {
  'use strict';

  const MAX_TRABALHADORES = 32;
  const FRAME_W = 720, FRAME_H = 480;        // resolução da câmera do detector (python/detector.py)

  const num = (v) => (v === null || v === undefined || v === '' ? NaN : Number(v));
  const fin = (v) => Number.isFinite(num(v));
  const conf = (v) => { const n = num(v); return Number.isFinite(n) ? Math.min(1, Math.max(0, n)) : null; };
  const bool = (v) => (v === undefined || v === null ? null : !!v);
  const pick = (o, ...chaves) => { for (const k of chaves) if (o[k] !== undefined) return o[k]; return undefined; };

  function statusDe(ppe, inRisk) {
    if (inRisk) return 'risk';
    if (ppe.helmet === false || ppe.vest === false) return 'violation';
    if (ppe.helmet === true && ppe.vest === true) return 'safe';
    return 'unknown';
  }

  function normalizarBox(b) {
    if (!Array.isArray(b) || b.length !== 4 || !b.every(fin)) return null;
    const [x1, y1, x2, y2] = b.map(Number);
    return [Math.min(x1, x2), Math.min(y1, y2), Math.max(x1, x2), Math.max(y1, y2)];
  }

  /** Converte UM trabalhador bruto. Retorna { trabalhador } ou { erro }. */
  function normalizarTrabalhador(m) {
    if (!m || typeof m !== 'object') return { erro: 'item não é um objeto' };
    const idBruto = pick(m, 'id', 'track_id', 'trackId');
    if (idBruto === undefined || idBruto === null || String(idBruto).trim() === '') return { erro: 'sem id' };
    const id = String(idBruto).trim().slice(0, 32);

    let position = null;
    const p = m.position;
    if (p && typeof p === 'object' && fin(p.x) && fin(p.z)) position = { x: +p.x, z: +p.z };
    else if (fin(m.x) && fin(m.z)) position = { x: +m.x, z: +m.z };

    const bbox = normalizarBox(pick(m, 'bbox', 'box_xyxy', 'box'));
    const image = bbox ? { bbox, foot: [(bbox[0] + bbox[2]) / 2, bbox[3]] } : null;   // ponto de contato com o chão

    const ppeIn = (m.ppe && typeof m.ppe === 'object') ? m.ppe : {};
    const ppe = {
      helmet: bool(pick(ppeIn, 'helmet', 'capacete') ?? pick(m, 'capacete', 'tem_capacete', 'helmet')),
      vest: bool(pick(ppeIn, 'vest', 'colete') ?? pick(m, 'colete', 'tem_colete', 'vest')),
    };
    const c = (m.confidence && typeof m.confidence === 'object') ? m.confidence : {};
    const confidence = {
      person: conf(pick(c, 'person', 'pessoa') ?? m.conf_pessoa),
      helmet: conf(pick(c, 'helmet', 'capacete') ?? m.conf_capacete),
      vest: conf(pick(c, 'vest', 'colete') ?? m.conf_colete),
    };
    const riscoBruto = pick(m, 'inRisk', 'risco_detectado', 'in_risk');
    const riskZoneIds = Array.isArray(m.riskZoneIds) ? m.riskZoneIds.map(String).slice(0, 8) : [];
    const inRisk = riscoBruto === undefined ? (riskZoneIds.length ? true : null) : !!riscoBruto;
    const direction = fin(m.direction) ? +m.direction : null;

    return { trabalhador: { id, position, direction, ppe, confidence, riskZoneIds, inRisk, status: statusDe(ppe, inRisk), image } };
  }

  /** Converte uma mensagem bruta (string JSON ou objeto). Retorna { frame, invalidos, erro }. */
  function normalizarMensagem(bruto, agora) {
    let dado = bruto;
    if (typeof bruto === 'string') {
      try { dado = JSON.parse(bruto); } catch (e) { return { frame: null, invalidos: 0, erro: 'JSON inválido' }; }
    }
    if (dado === null || typeof dado !== 'object') return { frame: null, invalidos: 0, erro: 'mensagem vazia' };

    const lista = Array.isArray(dado) ? dado
      : Array.isArray(dado.workers) ? dado.workers
      : Array.isArray(dado.operarios) ? dado.operarios
      : [dado];
    const meta = Array.isArray(dado) ? {} : dado;

    const workers = []; let invalidos = 0; const vistos = new Set();
    for (const item of lista.slice(0, MAX_TRABALHADORES)) {
      const r = normalizarTrabalhador(item);
      if (r.erro || vistos.has(r.trabalhador.id)) { invalidos++; continue; }
      vistos.add(r.trabalhador.id); workers.push(r.trabalhador);
    }
    if (lista.length > MAX_TRABALHADORES) invalidos += lista.length - MAX_TRABALHADORES;
    // lista vazia e válida (nenhuma pessoa na cena) é um quadro legítimo; objeto sem nenhum campo conhecido não é
    if (!workers.length && invalidos && !Array.isArray(meta.workers) && !Array.isArray(meta.operarios) && !Array.isArray(dado)) {
      return { frame: null, invalidos, erro: 'formato não reconhecido' };
    }
    const ts = fin(meta.timestamp) ? +meta.timestamp : null;
    const seq = fin(meta.sequence) ? Math.trunc(+meta.sequence) : null;
    return { frame: { source: 'real', timestamp: ts, sequence: seq, receivedAt: agora, workers }, invalidos, erro: null };
  }

  /** Controlador de fonte "real": estado de conexão, descarte de quadros velhos, quadro mais recente. */
  function criarFonte(opcoes) {
    const o = Object.assign({ staleMs: 3000, relogio: () => Date.now(), aoMudarEstado: () => {}, aoLog: () => {},
                              criarSocket: (url) => new WebSocket(url), atrasosReconexao: [1000, 2000, 4000, 8000, 15000] }, opcoes || {});
    const st = { estado: 'inativa', rotulo: '', url: '', canal: null,
                 recebidos: 0, descartados: 0, invalidos: 0, ultimoEm: 0, ultimaSeq: null, latenciaMs: null, taxa: 0 };
    let sock = null, timerReconectar = 0, tentativas = 0, desejada = false, pendente = null, janela = [], timerStale = 0;

    const mudar = (estado, rotulo) => {
      if (st.estado === estado && st.rotulo === rotulo) return;
      st.estado = estado; st.rotulo = rotulo || ''; o.aoMudarEstado(Object.assign({}, st));
    };

    function receber(bruto) {
      const agora = o.relogio();
      const r = normalizarMensagem(bruto, agora);
      if (!r.frame) { st.invalidos++; return false; }
      st.invalidos += r.invalidos;
      const f = r.frame;
      if (f.sequence !== null && st.ultimaSeq !== null && f.sequence <= st.ultimaSeq && st.ultimaSeq - f.sequence < 1000) {
        st.descartados++; return false;                          // quadro fora de ordem ou repetido
      }
      if (f.sequence !== null) st.ultimaSeq = f.sequence;
      st.recebidos++; st.ultimoEm = agora; pendente = f;
      if (f.timestamp !== null && Math.abs(agora - f.timestamp) < 6e4) st.latenciaMs = Math.max(0, agora - f.timestamp);
      janela.push(agora); while (janela.length && agora - janela[0] > 2000) janela.shift();
      st.taxa = janela.length / 2;
      mudar('ativa', 'recebendo dados reais');
      return true;
    }

    function verificar() {
      if (st.estado === 'ativa' && o.relogio() - st.ultimoEm > o.staleMs) {
        pendente = null; st.taxa = 0; janela = []; mudar('sem-sinal', 'sem mensagens há mais de ' + Math.round(o.staleMs / 1000) + ' s');
      }
    }
    const iniciarVigia = () => { if (!timerStale) timerStale = setInterval(verificar, 500); };
    const pararVigia = () => { clearInterval(timerStale); timerStale = 0; };

    function limparSocket() {
      clearTimeout(timerReconectar);
      if (sock) { const s0 = sock; sock = null; s0.onopen = s0.onmessage = s0.onerror = s0.onclose = null; try { s0.close(); } catch (e) { /* já fechado */ } }
    }
    function agendarReconexao() {
      if (!desejada || !st.url) return;
      const atraso = o.atrasosReconexao[Math.min(tentativas, o.atrasosReconexao.length - 1)]; tentativas++;
      mudar('desconectada', 'reconectando em ' + Math.round(atraso / 1000) + ' s');
      timerReconectar = setTimeout(abrir, atraso);
    }
    function abrir() {
      if (!desejada) return;
      mudar('conectando', 'conectando a ' + st.url);
      let s0, abriu = false;
      try { s0 = o.criarSocket(st.url); } catch (e) { mudar('erro', 'endereço inválido'); desejada = false; return; }
      sock = s0;
      const limite = setTimeout(() => { if (!abriu && sock === s0) { limparSocket(); agendarReconexao(); } }, 6000);
      s0.onopen = () => { abriu = true; clearTimeout(limite); tentativas = 0; mudar('aguardando', 'conectado; aguardando o primeiro quadro'); };
      s0.onmessage = (ev) => receber(ev.data);
      s0.onerror = () => { /* o onclose cuida da reconexão */ };
      s0.onclose = () => { clearTimeout(limite); if (sock === s0) { sock = null; pendente = null; agendarReconexao(); } };
    }

    return {
      /** Conecta a um WebSocket externo (modo avançado / servidor de testes). */
      conectarWS(url) {
        if (!/^wss?:\/\//i.test(url || '')) { mudar('erro', 'use um endereço ws:// ou wss://'); return false; }
        this.parar(); desejada = true; st.url = url; st.canal = 'websocket'; tentativas = 0; iniciarVigia(); abrir(); return true;
      },
      /** Usa um canal já existente (ex.: o socket do painel Arduino): quem chama repassa as mensagens a receber(). */
      usarCanal(nome, conectado) {
        this.parar(); st.canal = nome; st.url = ''; iniciarVigia();
        mudar(conectado ? 'aguardando' : 'desconectada', conectado ? 'canal ' + nome + ' ativo; aguardando o primeiro quadro' : 'canal ' + nome + ' sem conexão');
      },
      canalConectou(sim) {
        if (st.canal === 'painel' || (st.canal && st.canal !== 'websocket')) {
          if (!sim) { pendente = null; mudar('desconectada', 'canal ' + st.canal + ' sem conexão'); }
          else if (st.estado === 'desconectada') mudar('aguardando', 'canal reconectado; aguardando o primeiro quadro');
        }
      },
      receber,
      /** Devolve o quadro mais novo ainda não consumido (ou null). Várias mensagens por frame viram uma só atualização. */
      consumir() { const f = pendente; pendente = null; return f; },
      parar() { desejada = false; limparSocket(); pararVigia(); pendente = null; st.canal = null; st.url = ''; st.ultimaSeq = null; janela = []; st.taxa = 0; tentativas = 0; mudar('inativa', ''); },
      estado() { return Object.assign({}, st); },
      verificar,
    };
  }

  const api = { normalizarMensagem, normalizarTrabalhador, criarFonte, statusDe, FRAME_W, FRAME_H, MAX_TRABALHADORES };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else raiz.GemeoFonte = api;
})(typeof window !== 'undefined' ? window : globalThis);
