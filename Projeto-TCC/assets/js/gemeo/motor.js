/* =========================================================================
   motor.js — Núcleo do Gêmeo 3D (Three.js + CV + Replay + Calibração)
   -------------------------------------------------------------------------
   Controla TODA a lógica 3D do gêmeo digital. Carregado como script clássico
   (sem módulos) depois de Three.js e dos demais arquivos em js/gemeo/, dentro
   de um IIFE para não vazar nada para o escopo global (só GemeoMotor e
   window.__GEMEO_3D vistos por interface.js e pela tela).

   ÍNDICE NUMERADO DE SUBSISTEMAS (a ordem abaixo é a ordem física do arquivo;
   os subsistemas 3 a 7 vivem dentro da megafunção initTwin, por isso seus
   divisores aparecem indentados no meio dela):

   1. ESCALA E ESTADO — constantes W/H/B, grades 80x60, mundo 40x30 m,
      câmeras CAMS, canvas da planta e estado da visão computacional.
   2. VISÃO COMPUTACIONAL 2D E LIMPEZA DE PLANTA — drawSample(), scanPlan()
      (limiar adaptativo + detecção de portais), fechamento morfológico e
      desenho ao vivo na planta.
   3. CONSTRUÇÃO 3D E GREEDY MESHING — initTwin(): cena Three.js, paredes
      extrudadas PBR, pilares, piso, teto e malha agrupada por material.
   4. POOL DE AVATARES E TOTENS TÁCTICOS — createWorker(): avatar Layer 1
      (CCTV) e totem Layer 2 (mapa 3D), estados de EPI/risco e billboards.
   5. CÂMERAS PTZ E MONITOR CCTV — CAM 1A/1B/2A, fov/pos/target, CanvasTexture
      do monitor, câmera orbital e seletor de câmeras.
   6. MAPA DE CALOR E REPLAY CAIXA-PRETA — heatGrid/heatTex, carimbo de
      exposição/taxa e replay temporal de trilha (trailFor / playReplay).
   7. CALIBRADOR DE HOMOGRAFIA E SNAPSHOT — 4 cliques imagem<->planta, matriz H,
      persistência em localStorage + sincronia GET/POST /calibracao.
   8. PONTE DE DADOS REAIS E LOOP DE RENDERIZAÇÃO — fonte simulada vs. real
      (GemeoFonte.criarFonte), setRealData() e o laço animate().
   ========================================================================= */
(function () {
  'use strict';

  // =========================================================================
  // ===== 1. ESCALA E ESTADO =====
  // =========================================================================
  // ---------- Constantes de escala ----------
  const W = 320, H = 240, B = 4;                 // canvas 2D e bloco de varredura (4x4 px)
  const COLS = W / B, ROWS = H / B;              // grade de 80 x 60 blocos
  const CELL = 0.5;                              // 1 bloco = 0,5 m no mundo 3D
  const WW = COLS * CELL, WH = ROWS * CELL;      // galpÃ£o de 40 m x 30 m
  const WALL_H = 2.8;                            // altura das paredes (eixo Y)
  const THR = 5;                                 // pixels (de 16) para classificar o bloco desenhado
  const META = 95;                               // meta de conformidade do TCC (%)
  const SAMPLE_DT = 0.25;

  const CAMS = [
    { id: '1A', name: 'CAM 1A', sector: 'Corredor Central', pos: [0.5, 2.45, -13.3], target: [2.5, 0, -5.5], wall: [0, -1], fov: 62 },
    { id: '1B', name: 'CAM 1B', sector: 'Sala de MÃ¡quinas', pos: [18.0, 2.45, 1.1], target: [13.0, 0, 6.6], wall: [1, -1], fov: 66, ptz: true },
    { id: '2A', name: 'CAM 2A', sector: 'Almoxarifado / Prateleiras', pos: [-6.6, 2.45, 2.25], target: [2.5, 0, 3.4], wall: [-1, 0], fov: 62, ptz: true },
  ];

  const $ = (id) => document.getElementById(id);
  const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const fmt = (n) => n.toLocaleString('pt-BR');
  const f1 = (n) => n.toFixed(1).replace('.', ',').replace('-', 'âˆ’');

  // ---------- Chamadas HTTP para o backend (mesmo estilo de assets/js/api.js) ----------
  // motor.js carrega como script clássico (não pode importar módulos), então
  // repete aqui o cliente de mesma-origem com o cabeçalho X-Requested-With.
  function apiJson(url, opcoes) {
    const cfg = opcoes || {};
    return fetch(url, {
      method: cfg.method || 'GET',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'painel' },
      body: cfg.corpo ? JSON.stringify(cfg.corpo) : undefined,
      credentials: 'same-origin',
    }).then((r) => {
      if (r.status === 401) { window.dispatchEvent(new CustomEvent('sessao-expirada')); throw new Error('HTTP 401 em ' + url); }
      if (!r.ok) throw new Error('HTTP ' + r.status + ' em ' + url);
      return r.json();
    });
  }
  // ---------- Canvas da planta e da sobreposição ----------
  const plan = $('plan'), ctx = plan.getContext('2d', { willReadFrequently: true });
  const ov = $('overlay'), octx = ov.getContext('2d');
  const rawUploadCanvas = document.createElement('canvas');
  rawUploadCanvas.width = 640; rawUploadCanvas.height = 480;
  const rawUploadCtx = rawUploadCanvas.getContext('2d', { willReadFrequently: true });
  let hasRawUpload = false;

  // ---------- Estado da visão computacional ----------
  const wallGrid = new Uint8Array(COLS * ROWS);
  const riskGrid = new Uint8Array(COLS * ROWS);
  const doorGrid = new Uint8Array(COLS * ROWS);  // cÃ©lulas onde a CV detectou vÃ£o de porta/passagem
  const pass = new Uint8Array(COLS * ROWS);
  let wallCount = 0, riskCount = 0, freeList = [], riskList = [];
  let wallBoxes = 0, pillarCount = 0, doorCount = 0, riskZonesCount = 0;
  let planBounds = null;
  let source = 'planta de exemplo', dirty = false, twin = null;
  let activeCam = 0, wallAtStart = 0;
  const camYaw = CAMS.map((d) => Math.atan2(d.target[2] - d.pos[2], d.target[0] - d.pos[0]));
  // =========================================================================
  // ---------- Replay "caixa-preta" e calibração: ganchos dos subsistemas 6 e 7 ----------
  // (o código desses dois subsistemas vive dentro de initTwin)
  let trailFor = null, playReplay = null;
  const calibs = CAMS.map(() => null);                 // homografia por cÃ¢mera: { world, img, plan, H }
  const calibState = { on: false, cur: null };         // calibraÃ§Ã£o em andamento (pontos clicados)
  // Restaura calibraÃ§Ãµes salvas (persistem entre recarregamentos de pÃ¡gina).
  try {
    const saved = localStorage.getItem('epi.gemeo.calibs');
    if (saved) {
      const parsed = JSON.parse(saved);
      if (Array.isArray(parsed)) parsed.forEach((c, i) => { if (c) calibs[i] = c; });
    }
  // Sincroniza com a calibracao persistida no backend (GET /calibracao)
  try {
    fetch('/calibracao').then(r => r.ok ? r.json() : null).then(d => {
      if (d && d.H && d.camId) {
        const idx = CAMS.findIndex(c => c.id === d.camId);
        if (idx >= 0) { calibs[idx] = { world: d.world, img: d.img, plan: d.plan, H: d.H, frame: d.frame || { w: 640, h: 480 } }; }
      }
    }).catch(() => { /* backend indisponivel */ });
  } catch (e) { /* fetch nao disponivel */ }
  } catch (e) { /* localStorage indisponível ou dados corrompidos */ }

  // ---------- Registro de eventos ----------
  const logEl = $('log');
  const logItems = [];
  function logEvent(text, kind) {
    const t = new Date().toLocaleTimeString('pt-BR', { hour12: false });
    logItems.unshift({ t, text, kind: kind || '', trail: (kind === 'alert' && trailFor) ? trailFor(text) : null });
    if (logItems.length > 40) logItems.pop();
    logEl.innerHTML = '';
    logItems.forEach((it) => {
      const li = document.createElement('li');
      if (it.kind) li.className = it.kind;
      const tm = document.createElement('time'); tm.textContent = it.t;
      const sp = document.createElement('span'); sp.textContent = it.text;
      li.appendChild(tm); li.appendChild(sp);
      if (it.trail) {
        const rb = document.createElement('button'); rb.type = 'button'; rb.className = 'replay-btn'; rb.textContent = 'â–¶ Replay 3D';
        rb.title = 'Reproduzir no 3D o caminho percorrido atÃ© esta ocorrÃªncia';
        rb.addEventListener('click', () => { if (playReplay) playReplay(it.trail, it.t); });
        li.appendChild(rb);
      }
      logEl.appendChild(li);
    });
  }
  // =========================================================================
  // ===== 2. VISÃO COMPUTACIONAL 2D E LIMPEZA DE PLANTA =====
  // =========================================================================

  // ---------- Planta de exemplo ----------
  function drawSample() {
    ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = '#ef4444';
    ctx.fillRect(140, 30, 64, 52);
    ctx.beginPath();
    ctx.moveTo(250, 170); ctx.lineTo(300, 170); ctx.lineTo(300, 214);
    ctx.lineTo(274, 214); ctx.lineTo(274, 194); ctx.lineTo(250, 194);
    ctx.closePath(); ctx.fill();
    ctx.strokeStyle = '#000000'; ctx.lineWidth = 8; ctx.lineCap = 'butt'; ctx.lineJoin = 'miter';
    ctx.strokeRect(8, 8, 304, 224);
    const seg = (a, b, c, d) => { ctx.beginPath(); ctx.moveTo(a, b); ctx.lineTo(c, d); ctx.stroke(); };
    seg(100, 8, 100, 64); seg(100, 98, 100, 232);                      // porta vertical
    seg(8, 130, 46, 130); seg(76, 130, 100, 130);                      // porta horizontal
    seg(228, 120, 312, 120); seg(228, 120, 228, 136); seg(228, 168, 228, 232); // porta sala mÃ¡quinas
    ctx.fillStyle = '#000000';
    ctx.fillRect(136, 116, 64, 10); ctx.fillRect(136, 150, 64, 10); ctx.fillRect(136, 184, 64, 10);
  }
  function clearPlan() { ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, W, H); }

  // ---------- Motor de VisÃ£o Computacional v5 (Limiar Adaptativo + DetecÃ§Ã£o de Portais) ----------
  function scanPlan() {
    const data = ctx.getImageData(0, 0, W, H).data;
    const useAdapt = $('adapt') ? $('adapt').checked : true;
    const wallThr = source.startsWith('imagem') ? 2 : THR;
    wallGrid.fill(0); riskGrid.fill(0); doorGrid.fill(0);
    wallCount = 0; riskCount = 0;

    // Calcula luminÃ¢ncia mÃ©dia por bloco para compensar sombras em fotos de plantas
    const blockLum = new Float32Array(COLS * ROWS);
    for (let by = 0; by < ROWS; by++) {
      for (let bx = 0; bx < COLS; bx++) {
        let sum = 0;
        for (let y = 0; y < B; y++) {
          let i = ((by * B + y) * W + bx * B) * 4;
          for (let x = 0; x < B; x++, i += 4) sum += 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
        }
        blockLum[by * COLS + bx] = sum / 16;
      }
    }

    for (let by = 0; by < ROWS; by++) {
      for (let bx = 0; bx < COLS; bx++) {
        // MÃ©dia local 7x7 blocos ao redor para limiar adaptativo
        let localSum = 0, localCnt = 0;
        if (useAdapt) {
          for (let dy = -3; dy <= 3; dy++) {
            for (let dx = -3; dx <= 3; dx++) {
              const ny = by + dy, nx = bx + dx;
              if (ny >= 0 && ny < ROWS && nx >= 0 && nx < COLS) {
                localSum += blockLum[ny * COLS + nx];
                localCnt++;
              }
            }
          }
        }
        const localMean = useAdapt ? (localSum / localCnt) : 255;
        const darkCut = useAdapt ? Math.min(115, Math.max(55, localMean * 0.62)) : 80;

        let dark = 0, red = 0;
        for (let y = 0; y < B; y++) {
          let i = ((by * B + y) * W + bx * B) * 4;
          for (let x = 0; x < B; x++, i += 4) {
            const R = data[i], G = data[i + 1], Bl = data[i + 2];
            const lum = 0.299 * R + 0.587 * G + 0.114 * Bl;
            if (R > 155 && R > G * 1.45 && R > Bl * 1.45 && (R - Math.max(G, Bl)) > 45) red++;
            else if (lum < darkCut) dark++;
          }
        }
        const idx = by * COLS + bx;
        if (dark >= wallThr && dark >= red) { wallGrid[idx] = 1; wallCount++; }
        else if (red >= THR) { riskGrid[idx] = 1; riskCount++; }
      }
    }

    // Fechamento morfolÃ³gico leve: remove micro-buracos de 1 cÃ©lula isolada dentro de paredes grossas
    const copyW = new Uint8Array(wallGrid);
    for (let r = 1; r < ROWS - 1; r++) {
      for (let c = 1; c < COLS - 1; c++) {
        const idx = r * COLS + c;
        if (!copyW[idx]) {
          const n = copyW[(r - 1) * COLS + c] + copyW[(r + 1) * COLS + c] + copyW[r * COLS + c - 1] + copyW[r * COLS + c + 1];
          if (n >= 4) { wallGrid[idx] = 1; wallCount++; }
        }
      }
    }

    // Em uploads, preserva somente traÃ§os estruturais ortogonais e a malha principal da casa.
    if (source.startsWith('imagem')) {
      const base = new Uint8Array(wallGrid), manhattan = new Uint8Array(COLS * ROWS);
      const runH = (r, c) => {
        let n = 1, x = c - 1; while (x >= 0 && base[r * COLS + x]) { n++; x--; }
        x = c + 1; while (x < COLS && base[r * COLS + x]) { n++; x++; }
        return n;
      };
      const runV = (r, c) => {
        let n = 1, y = r - 1; while (y >= 0 && base[y * COLS + c]) { n++; y--; }
        y = r + 1; while (y < ROWS && base[y * COLS + c]) { n++; y++; }
        return n;
      };
      for (let r = 0; r < ROWS; r++) for (let c = 0; c < COLS; c++) {
        const i = r * COLS + c;
        if (base[i] && (runH(r, c) >= 3 || runV(r, c) >= 3)) manhattan[i] = 1;
      }
      // MantÃ©m quinas que tocam corridas H/V vÃ¡lidas, sem reintroduzir arcos e curvas isoladas.
      for (let r = 1; r < ROWS - 1; r++) for (let c = 1; c < COLS - 1; c++) {
        const i = r * COLS + c;
        if (!base[i] || manhattan[i]) continue;
        const orth = manhattan[(r - 1) * COLS + c] + manhattan[(r + 1) * COLS + c] + manhattan[r * COLS + c - 1] + manhattan[r * COLS + c + 1];
        if (orth >= 2) manhattan[i] = 1;
      }
      wallGrid.set(manhattan);
      const seen = new Uint8Array(COLS * ROWS), comps = [], dirs = [-1, -1, 0, -1, 1, -1, -1, 0, 1, 0, -1, 1, 0, 1, 1, 1];
      for (let r = 0; r < ROWS; r++) for (let c = 0; c < COLS; c++) {
        const start = r * COLS + c;
        if (!wallGrid[start] || seen[start]) continue;
        const cells = [start]; seen[start] = 1;
        for (let q = 0; q < cells.length; q++) {
          const at = cells[q], ar = Math.floor(at / COLS), ac = at % COLS;
          for (let d = 0; d < dirs.length; d += 2) {
            const nc = ac + dirs[d], nr = ar + dirs[d + 1];
            if (nc < 0 || nc >= COLS || nr < 0 || nr >= ROWS) continue;
            const ni = nr * COLS + nc;
            if (wallGrid[ni] && !seen[ni]) { seen[ni] = 1; cells.push(ni); }
          }
        }
        comps.push(cells);
      }
      const maxCompSize = comps.reduce((max, cells) => Math.max(max, cells.length), 0);
      const minStructuralSize = Math.max(18, Math.ceil(maxCompSize * 0.08));
      comps.forEach((cells) => { if (cells.length < minStructuralSize) cells.forEach((i) => { wallGrid[i] = 0; }); });
    }

    wallCount = 0;
    let minCol = COLS, minRow = ROWS, maxCol = -1, maxRow = -1;
    wallGrid.forEach((v, i) => {
      if (!v) return;
      wallCount++;
      const c = i % COLS, r = Math.floor(i / COLS);
      minCol = Math.min(minCol, c); maxCol = Math.max(maxCol, c);
      minRow = Math.min(minRow, r); maxRow = Math.max(maxRow, r);
    });
    planBounds = maxCol >= minCol ? { minCol, minRow, maxCol, maxRow } : null;

    computePassable();
    $('wallCount').textContent = fmt(wallCount);
    $('riskCount').textContent = fmt(riskCount);
    updateWallAux();
    $('riskAux').textContent = 'â‰ˆ ' + f1(riskCount * CELL * CELL) + ' mÂ²' + (riskZonesCount ? ' Â· ' + riskZonesCount + ' zonas' : '');
  }

  function updateWallAux() {
    $('wallAux').textContent = fmt(wallBoxes) + ' vigas Â· ' + fmt(pillarCount) + ' pilares Â· ' + fmt(doorCount) + ' portais';
  }

  function processPlan(reason) {
    scanPlan();
    dirty = false; updateNote();
    animateOverlay();
    if (twin) { twin.autoPlaceCams(); twin.rebuild(true); }
    logEvent((reason || 'ExtrusÃ£o 3D concluÃ­da') + ': ' + fmt(wallBoxes) + ' paredes, ' + fmt(doorCount) + ' portais e ' + fmt(riskCount) + ' cÃ©lulas de risco.');
  }

  let softTimer = 0, softPending = false;
  function softUpdate() {
    cancelAnimationFrame(scanRAF);
    scanPlan(); dirty = false; updateNote();
    if (twin) { twin.autoPlaceCams(); twin.rebuildMeshes(false); }
    drawOverlay(COLS, false);
  }
  function scheduleSoft() {
    if (softTimer) { softPending = true; return; }
    softUpdate();
    softTimer = setTimeout(() => { softTimer = 0; if (softPending) { softPending = false; scheduleSoft(); } }, 90);
  }

  function computePassable() {
    pass.fill(0); freeList = []; riskList = [];
    for (let r = 0; r < ROWS; r++) {
      for (let c = 0; c < COLS; c++) {
        let ok = true;
        scan: for (let dr = -1; dr <= 1; dr++) {
          for (let dc = -1; dc <= 1; dc++) {
            const rr = r + dr, cc = c + dc;
            if (rr < 0 || cc < 0 || rr >= ROWS || cc >= COLS || wallGrid[rr * COLS + cc]) { ok = false; break scan; }
          }
        }
        if (ok) {
          const idx = r * COLS + c;
          pass[idx] = 1;
          (riskGrid[idx] ? riskList : freeList).push(idx);
        }
      }
    }
  }

  function updateNote() {
    const el = $('planNote');
    if (dirty) { el.textContent = 'Planta editada. Clique em Processar para atualizar o 3D.'; el.className = 'dirty'; }
    else { el.textContent = 'Fonte: ' + source; el.className = ''; }
  }

  let scanRAF = 0;
  function drawOverlay(upTo, scanning) {
    octx.clearRect(0, 0, W, H);
    for (let r = 0; r < ROWS; r++) {
      for (let c = 0; c <= upTo && c < COLS; c++) {
        const i = r * COLS + c;
        if (wallGrid[i]) { octx.fillStyle = 'rgba(90,169,230,0.62)'; octx.fillRect(c * B, r * B, B, B); }
        else if (doorGrid[i]) { octx.fillStyle = 'rgba(56,189,248,0.55)'; octx.fillRect(c * B, r * B, B, B); }
        else if (riskGrid[i]) { octx.fillStyle = 'rgba(242,183,5,0.58)'; octx.fillRect(c * B, r * B, B, B); }
      }
    }
    if (scanning) { octx.fillStyle = 'rgba(182,255,59,0.95)'; octx.fillRect(Math.min(W - 2, (upTo + 1) * B), 0, 2, H); }
  }
  function animateOverlay() {
    cancelAnimationFrame(scanRAF);
    const dur = reduceMotion ? 0 : 650, t0 = performance.now();
    (function frame(now) {
      const p = dur ? Math.min(1, (now - t0) / dur) : 1;
      drawOverlay(Math.floor(p * COLS), p < 1);
      if (p < 1) scanRAF = requestAnimationFrame(frame);
    })(t0);
  }

  // ---------- Desenho ao vivo na planta ----------
  let tool = 'wall', drawing = false, lastPt = null;
  const live = () => $('auto').checked && (tool === 'risk' || tool === 'erase');
  const COLORS = { wall: '#000000', risk: '#ef4444', erase: '#ffffff' };
  const sizeEl = $('size');
  sizeEl.addEventListener('input', () => { $('sizeOut').textContent = sizeEl.value + ' px'; });
  document.querySelectorAll('[data-tool]').forEach((b) => {
    b.addEventListener('click', () => {
      tool = b.dataset.tool;
      document.querySelectorAll('[data-tool]').forEach((o) => o.setAttribute('aria-pressed', String(o === b)));
    });
  });
  function pt(e) {
    const r = plan.getBoundingClientRect();
    return { x: (e.clientX - r.left) * W / r.width, y: (e.clientY - r.top) * H / r.height };
  }
  plan.addEventListener('pointerdown', (e) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    e.preventDefault();
    plan.setPointerCapture(e.pointerId);
    drawing = true; lastPt = pt(e); wallAtStart = wallCount;
    const s = +sizeEl.value;
    ctx.fillStyle = COLORS[tool];
    ctx.beginPath(); ctx.arc(lastPt.x, lastPt.y, s / 2, 0, Math.PI * 2); ctx.fill();
    markDirty();
    if (live()) scheduleSoft();
  });
  plan.addEventListener('pointermove', (e) => {
    if (!drawing) return;
    const p = pt(e);
    ctx.strokeStyle = COLORS[tool]; ctx.lineWidth = +sizeEl.value; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.beginPath(); ctx.moveTo(lastPt.x, lastPt.y); ctx.lineTo(p.x, p.y); ctx.stroke();
    lastPt = p;
    if (live()) scheduleSoft();
  });
  function endDraw() {
    if (!drawing) return;
    drawing = false;
    if ($('auto').checked) {
      if (tool === 'wall') processPlan('Planta editada');
      else {
        softUpdate();
        if (wallCount !== wallAtStart) processPlan('Planta editada');
        else logEvent('Ãrea de risco ' + (tool === 'risk' ? 'pintada' : 'apagada') + ' na planta: ' + fmt(riskCount) + ' cÃ©lulas de risco.');
      }
    }
  }
  plan.addEventListener('pointerup', endDraw);
  plan.addEventListener('pointercancel', endDraw);
  function markDirty() { dirty = true; source = 'planta editada'; updateNote(); }

  $('process').addEventListener('click', () => processPlan('ExtrusÃ£o 3D atualizada'));
  $('sample').addEventListener('click', () => { drawSample(); source = 'planta de exemplo'; processPlan('Planta de exemplo carregada'); });
  $('clear').addEventListener('click', () => { clearPlan(); source = 'planta em branco'; processPlan('Planta limpa'); });
  $('showGrid').addEventListener('change', (e) => { ov.hidden = !e.target.checked; });
  $('adapt').addEventListener('change', () => processPlan('Filtro Anti-Sombra atualizado'));

  function renderCleanUpload(reason) {
    if (!hasRawUpload) return;
    const RW = rawUploadCanvas.width, RH = rawUploadCanvas.height, src = rawUploadCtx.getImageData(0, 0, RW, RH);
    const original = src.data, binary = new Uint8Array(RW * RH), kept = new Uint8Array(RW * RH), dilated = new Uint8Array(RW * RH);
    const strength = +$('thickFilter').value;
    const minNeighbors = Math.max(1, Math.min(25, 16 + (strength - 2) * 3));
    const isRed = (i) => original[i] > 155 && original[i] > original[i + 1] * 1.45 && original[i] > original[i + 2] * 1.45;
    for (let y = 0; y < RH; y++) for (let x = 0; x < RW; x++) {
      const i = (y * RW + x) * 4, lum = 0.299 * original[i] + 0.587 * original[i + 1] + 0.114 * original[i + 2];
      if (!isRed(i) && lum < 145) binary[y * RW + x] = 1;
    }
    for (let y = 0; y < RH; y++) for (let x = 0; x < RW; x++) {
      const id = y * RW + x;
      if (!binary[id]) continue;
      let count = 0;
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) {
        const ny = y + dy, nx = x + dx;
        if (ny >= 0 && ny < RH && nx >= 0 && nx < RW) count += binary[ny * RW + nx];
      }
      if (count >= minNeighbors) kept[id] = 1;
    }
    for (let y = 0; y < RH; y++) for (let x = 0; x < RW; x++) {
      const id = y * RW + x;
      if (!kept[id]) continue;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        const ny = y + dy, nx = x + dx;
        if (ny >= 0 && ny < RH && nx >= 0 && nx < RW) dilated[ny * RW + nx] = 1;
      }
    }
    const clean = rawUploadCtx.createImageData(RW, RH); let x0 = RW, y0 = RH, x1 = -1, y1 = -1;
    for (let y = 0; y < RH; y++) for (let x = 0; x < RW; x++) {
      const id = y * RW + x, i = id * 4, red = isRed(i), on = dilated[id] || red;
      clean.data[i] = on && !red ? 0 : red ? original[i] : 255;
      clean.data[i + 1] = on && !red ? 0 : red ? original[i + 1] : 255;
      clean.data[i + 2] = on && !red ? 0 : red ? original[i + 2] : 255;
      clean.data[i + 3] = 255;
      if (on) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
    }
    if (x1 < x0 || y1 < y0) { x0 = 0; y0 = 0; x1 = RW - 1; y1 = RH - 1; }
    const cleanedCanvas = document.createElement('canvas'); cleanedCanvas.width = RW; cleanedCanvas.height = RH;
    cleanedCanvas.getContext('2d').putImageData(clean, 0, 0);
    clearPlan();
    const cropW = x1 - x0 + 1, cropH = y1 - y0 + 1, scale = Math.min((W * 0.88) / cropW, (H * 0.88) / cropH);
    const dw = cropW * scale, dh = cropH * scale;
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(cleanedCanvas, x0, y0, cropW, cropH, (W - dw) / 2, (H - dh) / 2, dw, dh);
    ctx.imageSmoothingEnabled = true;
    processPlan(reason || 'Imagem limpa por filtro de espessura');
  }

  $('thickFilter').addEventListener('input', (e) => {
    $('thickFilterOut').textContent = e.target.value;
    if (hasRawUpload) renderCleanUpload('Filtro de espessura atualizado');
  });
  $('upload').addEventListener('click', () => $('file').click());
  $('file').addEventListener('change', (e) => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        rawUploadCtx.fillStyle = '#ffffff'; rawUploadCtx.fillRect(0, 0, rawUploadCanvas.width, rawUploadCanvas.height);
        const scale = Math.min(rawUploadCanvas.width / img.width, rawUploadCanvas.height / img.height);
        const w = img.width * scale, h = img.height * scale;
        rawUploadCtx.drawImage(img, (rawUploadCanvas.width - w) / 2, (rawUploadCanvas.height - h) / 2, w, h);
        hasRawUpload = true; source = 'imagem enviada (' + f.name + ')';
        renderCleanUpload('Imagem recortada e limpa por espessura');
      };
      img.onerror = () => logEvent('NÃ£o foi possÃ­vel ler a imagem. Tente PNG ou JPG.', 'alert');
      img.src = reader.result;
    };
    reader.readAsDataURL(f); e.target.value = '';
  });

  $('scan360').addEventListener('click', () => {
    if (!planBounds) { logEvent('Scan 360Â° indisponÃ­vel: nenhuma parede estrutural foi detectada.', 'alert'); return; }
    cancelAnimationFrame(scanRAF);
    const cx = (planBounds.minCol + planBounds.maxCol + 1) * B / 2, cy = (planBounds.minRow + planBounds.maxRow + 1) * B / 2;
    const halfW = (planBounds.maxCol - planBounds.minCol + 1) * CELL / 2;
    const halfH = (planBounds.maxRow - planBounds.minRow + 1) * CELL / 2;
    const cameraH = CAMS[activeCam].pos[1], opticalAngle = THREE.MathUtils.degToRad(34);
    const ranges = [];
    for (let a = 0; a < 360; a += 5) {
      const rad = a * Math.PI / 180, dx = Math.cos(rad), dz = Math.sin(rad);
      const tx = dx ? halfW / Math.abs(dx) : Infinity, tz = dz ? halfH / Math.abs(dz) : Infinity;
      ranges.push(Math.min(tx, tz));
    }
    const opticalDistance = cameraH / Math.tan(opticalAngle);
    const perimeter = 2 * (halfW * 2 + halfH * 2);
    const dur = reduceMotion ? 0 : 1100, started = performance.now();
    (function sweep(now) {
      const p = dur ? Math.min(1, (now - started) / dur) : 1;
      drawOverlay(COLS, false);
      octx.save(); octx.translate(cx, cy); octx.rotate(p * Math.PI * 2);
      octx.strokeStyle = 'rgba(56,189,248,0.95)'; octx.lineWidth = 2; octx.beginPath(); octx.moveTo(0, 0); octx.lineTo(Math.max(W, H), 0); octx.stroke();
      octx.strokeStyle = 'rgba(182,255,59,0.52)'; octx.beginPath(); octx.arc(0, 0, Math.min(W, H) * 0.42, 0, Math.PI * 2); octx.stroke(); octx.restore();
      if (p < 1) scanRAF = requestAnimationFrame(sweep);
      else {
        drawOverlay(COLS, false);
        logEvent('Scan 360Â° concluÃ­do: PerÃ­metro ' + f1(perimeter) + 'm Â· ' + f1(halfW * 2) + 'm Ã— ' + f1(halfH * 2) + 'm detectado via Telemetria Ã“ptica (d=' + f1(opticalDistance) + 'm; ' + ranges.length + ' raios).', 'ok');
      }
    })(started);
  });

  const bannerEl = $('banner'), bTitle = $('bannerTitle'), bSub = $('bannerSub');
  let bannerKey = '';
  function setBanner(state, title, sub) {
    const key = state + '|' + title + '|' + sub;
    if (key === bannerKey) return;
    bannerKey = key;
    bannerEl.dataset.state = state; bTitle.textContent = title; bSub.textContent = sub;
  }
  // =========================================================================
  // ===== 3. CONSTRUÇÃO 3D E GREEDY MESHING =====
  // =========================================================================

  // ---------- GÃªmeo Digital 3D v5.0 (Three.js + PBR + ExtrusÃ£o ArquitetÃ´nica) ----------
  function initTwin() {
    const viewer = $('viewer');
    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));   // teto de 1,5: acima disso o ganho visual Ã© pequeno e o custo de pixels cresce rÃ¡pido
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.shadowMap.autoUpdate = false;
    renderer.shadowMap.needsUpdate = true;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.08;
    const dom = renderer.domElement;
    viewer.insertBefore(dom, viewer.firstChild);

    const scene = new THREE.Scene();
    // Fundo azul-marinho profundo alinhado Ã  identidade visual do painel.
    // MantÃ©m a mesma iluminaÃ§Ã£o e o mesmo custo de renderizaÃ§Ã£o.
    scene.background = new THREE.Color(0x0a1424);
    scene.fog = new THREE.FogExp2(0x0a1424, 0.0092);
    const camera = new THREE.PerspectiveCamera(46, 1, 0.1, 300);
    camera.layers.enable(2);

    // IluminaÃ§Ã£o industrial multi-fonte (HemisfÃ©rica + Sol direcional + Preenchimento frio)
    scene.add(new THREE.HemisphereLight(0xd4e4f7, 0x18222f, 0.88));
    const sun = new THREE.DirectionalLight(0xfff7e8, 1.02);
    sun.position.set(-16, 32, 20);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.camera.left = -26; sun.shadow.camera.right = 26;
    sun.shadow.camera.top = 22; sun.shadow.camera.bottom = -22;
    sun.shadow.camera.near = 1; sun.shadow.camera.far = 95;
    sun.shadow.bias = -0.0005;
    scene.add(sun);

    const rimLight = new THREE.DirectionalLight(0x60a5fa, 0.35);
    rimLight.position.set(22, 18, -18);
    scene.add(rimLight);

    // Piso EpÃ³xi Industrial de alta definiÃ§Ã£o com juntas de dilataÃ§Ã£o e marcaÃ§Ãµes tÃ©cnicas
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(260, 220), new THREE.MeshStandardMaterial({ color: 0x090d13, roughness: 1 }));
    ground.rotation.x = -Math.PI / 2; ground.position.y = -0.34; scene.add(ground);

    const slab = new THREE.Mesh(new THREE.BoxGeometry(WW + 1.2, 0.32, WH + 1.2), new THREE.MeshStandardMaterial({ color: 0x24303f, roughness: 0.85, metalness: 0.1 }));
    slab.position.y = -0.17; slab.receiveShadow = true; scene.add(slab);

    const fc = document.createElement('canvas'); fc.width = fc.height = 256;
    const fx = fc.getContext('2d');
    fx.fillStyle = '#17263a'; fx.fillRect(0, 0, 256, 256);
    fx.fillStyle = '#1c3048'; fx.fillRect(0, 0, 128, 128); fx.fillRect(128, 128, 128, 128);
    fx.strokeStyle = 'rgba(145, 181, 222, 0.17)'; fx.lineWidth = 2;
    fx.strokeRect(0, 0, 128, 128); fx.strokeRect(128, 128, 128, 128);
    fx.strokeStyle = 'rgba(242, 183, 5, 0.18)'; fx.lineWidth = 1;
    fx.beginPath(); fx.moveTo(128, 0); fx.lineTo(128, 256); fx.moveTo(0, 128); fx.lineTo(256, 128); fx.stroke();
    const ftex = new THREE.CanvasTexture(fc);
    ftex.wrapS = ftex.wrapT = THREE.RepeatWrapping;
    ftex.repeat.set(WW / 4, WH / 4);
    ftex.anisotropy = renderer.capabilities.getMaxAnisotropy();
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(WW, WH), new THREE.MeshStandardMaterial({ map: ftex, roughness: 0.55, metalness: 0.12 }));
    floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);

    // Textura de parede de concreto / bloco estrutural e textura zebrada de risco
    const wc = document.createElement('canvas'); wc.width = wc.height = 128;
    const wx = wc.getContext('2d');
    wx.fillStyle = '#d5dde6'; wx.fillRect(0, 0, 128, 128);
    wx.fillStyle = 'rgba(0,0,0,0.04)';
    for (let y = 0; y < 128; y += 16) wx.fillRect(0, y, 128, 2);
    const wtex = new THREE.CanvasTexture(wc);
    wtex.wrapS = wtex.wrapT = THREE.RepeatWrapping;

    const hz = document.createElement('canvas'); hz.width = hz.height = 128;
    const hx = hz.getContext('2d');
    hx.fillStyle = '#991b1b'; hx.fillRect(0, 0, 128, 128);
    hx.strokeStyle = '#ef4444'; hx.lineWidth = 14;
    for (let k = -128; k < 256; k += 32) {
      hx.beginPath(); hx.moveTo(k, 0); hx.lineTo(k + 128, 128); hx.stroke();
    }
    hx.strokeStyle = '#facc15'; hx.lineWidth = 6;
    hx.strokeRect(3, 3, 122, 122);
    const htex = new THREE.CanvasTexture(hz);

    // Estrutura de Teto Industrial (TreliÃ§as metÃ¡licas + LuminÃ¡rias LED High-Bay)
    const roofGroup = new THREE.Group();
    const beamMat = new THREE.MeshStandardMaterial({ color: 0x263241, roughness: 0.5, metalness: 0.65, transparent: true, opacity: 0.88 });
    const lampMat = new THREE.MeshBasicMaterial({ color: 0xe0f2fe });
    for (let z = -WH / 2 + 5; z <= WH / 2 - 5; z += 10) {
      const beam = new THREE.Mesh(new THREE.BoxGeometry(WW - 1.5, 0.14, 0.18), beamMat);
      beam.position.set(0, WALL_H + 1.45, z);
      roofGroup.add(beam);
      for (let x = -WW / 2 + 6; x <= WW / 2 - 6; x += 9) {
        const fixture = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.06, 0.36), lampMat);
        fixture.position.set(x, WALL_H + 1.36, z);
        roofGroup.add(fixture);
      }
    }
    scene.add(roofGroup);
    $('toggleRoof').addEventListener('click', (e) => {
      roofGroup.visible = !roofGroup.visible;
      e.currentTarget.setAttribute('aria-pressed', String(roofGroup.visible));
      e.currentTarget.textContent = 'TreliÃ§as e iluminaÃ§Ã£o: ' + (roofGroup.visible ? 'ligadas' : 'desligadas');
    });

    // Malhas instanciadas para ExtrusÃ£o CAD/BIM (Paredes, Topo, RodapÃ©, Pilares H, Portais e Zonas de Risco)
    const MAXI = COLS * ROWS;
    const unitBox = new THREE.BoxGeometry(1, 1, 1);
    const wallMat = new THREE.MeshStandardMaterial({ map: wtex, color: 0xd8e0e8, roughness: 0.72, metalness: 0.08 });
    const capMat = new THREE.MeshStandardMaterial({ color: 0x2b3542, roughness: 0.55, metalness: 0.25 });
    const baseMat = new THREE.MeshStandardMaterial({ color: 0x4b596b, roughness: 0.8 });
    const pillarMat = new THREE.MeshStandardMaterial({ color: 0x3b82f6, roughness: 0.45, metalness: 0.5 });
    const lintelMat = new THREE.MeshStandardMaterial({ color: 0x475569, roughness: 0.52, metalness: 0.28 });
    const lintelStripeMat = new THREE.MeshBasicMaterial({ color: 0xf2b705 });

    const riskGeo = new THREE.BoxGeometry(1, 0.05, 1);
    const riskMat = new THREE.MeshStandardMaterial({ map: htex, color: 0xffdada, emissive: 0xdc2626, emissiveIntensity: 0.65, roughness: 0.45 });

    const buildGroup = new THREE.Group();
    scene.add(buildGroup);

    const wallMesh = new THREE.InstancedMesh(unitBox, wallMat, MAXI);
    const capMesh = new THREE.InstancedMesh(unitBox, capMat, MAXI);
    const baseMesh = new THREE.InstancedMesh(unitBox, baseMat, MAXI);
    const pillarMesh = new THREE.InstancedMesh(unitBox, pillarMat, MAXI);
    const lintelMesh = new THREE.InstancedMesh(unitBox, lintelMat, 512);
    const lintelStripeMesh = new THREE.InstancedMesh(unitBox, lintelStripeMat, 512);
    const riskMesh = new THREE.InstancedMesh(riskGeo, riskMat, MAXI);

    const edgeArr = new Float32Array(MAXI * 8 * 3);
    const edgeGeo = new THREE.BufferGeometry();
    edgeGeo.setAttribute('position', new THREE.BufferAttribute(edgeArr, 3));
    edgeGeo.setDrawRange(0, 0);
    const edges = new THREE.LineSegments(edgeGeo, new THREE.LineBasicMaterial({ color: 0xf1f5f9 }));

    [wallMesh, capMesh, baseMesh, pillarMesh, lintelMesh, lintelStripeMesh, riskMesh, edges].forEach((m) => {
      m.frustumCulled = false; m.count = 0; buildGroup.add(m);
    });
    wallMesh.castShadow = true; wallMesh.receiveShadow = true;
    pillarMesh.castShadow = true; lintelMesh.castShadow = true; baseMesh.receiveShadow = true;

    const cx = (c) => (c + 0.5) * CELL - WW / 2;
    const cz = (r) => (r + 0.5) * CELL - WH / 2;
    const toCol = (x) => Math.floor((x + WW / 2) / CELL);
    const toRow = (z) => Math.floor((z + WH / 2) / CELL);

    function greedyGrid(grid) {
      const used = new Uint8Array(COLS * ROWS), out = [];
      for (let r = 0; r < ROWS; r++) {
        for (let c = 0; c < COLS; c++) {
          const i = r * COLS + c;
          if (!grid[i] || used[i]) continue;
          let w = 1;
          while (c + w < COLS && grid[i + w] && !used[i + w]) w++;
          let h = 1;
          grow: while (r + h < ROWS) {
            for (let k = 0; k < w; k++) { const j = (r + h) * COLS + c + k; if (!grid[j] || used[j]) break grow; }
            h++;
          }
          for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) used[(r + y) * COLS + c + x] = 1;
          out.push([c, r, w, h]);
        }
      }
      return out;
    }

    // Portais ultra-restritos: vÃ£o de 2â€“4 cÃ©lulas, apoios contÃ­nuos e faces livres.
    function detectDoors() {
      doorGrid.fill(0);
      const doors = [], visited = new Uint8Array(COLS * ROWS);
      const at = (c, r) => c >= 0 && c < COLS && r >= 0 && r < ROWS && wallGrid[r * COLS + c] === 1;
      const free = (c, r) => c >= 0 && c < COLS && r >= 0 && r < ROWS && wallGrid[r * COLS + c] === 0;
      const runH = (c, r, dir) => at(c, r) && at(c + dir, r) && at(c + dir * 2, r);
      const runV = (c, r, dir) => at(c, r) && at(c, r + dir) && at(c, r + dir * 2);

      for (let r = 1; r < ROWS - 1; r++) {
        for (let c = 3; c < COLS - 6; c++) {
          if (wallGrid[r * COLS + c] || visited[r * COLS + c]) continue;
          for (let span = 2; span <= 4; span++) {
            if (!runH(c - 1, r, -1) || !runH(c + span, r, 1)) continue;
            let clearFaces = true;
            for (let k = 0; k < span; k++) if (!free(c + k, r) || !free(c + k, r - 1) || !free(c + k, r + 1)) { clearFaces = false; break; }
            if (!clearFaces) continue;
            for (let k = 0; k < span; k++) { doorGrid[r * COLS + c + k] = 1; visited[r * COLS + c + k] = 1; }
            doors.push({ c, r, w: span, h: 1, dir: 'h' }); c += span - 1; break;
          }
        }
      }
      for (let c = 1; c < COLS - 1; c++) {
        for (let r = 3; r < ROWS - 6; r++) {
          if (wallGrid[r * COLS + c] || visited[r * COLS + c]) continue;
          for (let span = 2; span <= 4; span++) {
            if (!runV(c, r - 1, -1) || !runV(c, r + span, 1)) continue;
            let clearFaces = true;
            for (let k = 0; k < span; k++) if (!free(c, r + k) || !free(c - 1, r + k) || !free(c + 1, r + k)) { clearFaces = false; break; }
            if (!clearFaces) continue;
            for (let k = 0; k < span; k++) { doorGrid[(r + k) * COLS + c] = 1; visited[(r + k) * COLS + c] = 1; }
            doors.push({ c, r, w: 1, h: span, dir: 'v' }); r += span - 1; break;
          }
        }
      }
      return doors;
    }

    let extrudeProgress = 1, shadowDirty = true;
    const m4 = new THREE.Matrix4(), qI = new THREE.Quaternion(), vP = new THREE.Vector3(), vS = new THREE.Vector3(), colW = new THREE.Color();

    function buildMeshes(animateExtrude) {
      shadowDirty = true;
      if (animateExtrude && !reduceMotion) extrudeProgress = 0.02;
      const rects = greedyGrid(wallGrid), n = rects.length;
      let pi = 0;

      rects.forEach(([c, r, w, h], i) => {
        const sx = w * CELL, sz = h * CELL, px = (c + w / 2) * CELL - WW / 2, pz = (r + h / 2) * CELL - WH / 2;
        const isShortPillar = (w <= 3 && h <= 3);
        m4.compose(vP.set(px, WALL_H / 2, pz), qI, vS.set(sx, WALL_H, sz)); wallMesh.setMatrixAt(i, m4);
        const sh = isShortPillar ? 0.78 : (0.92 + ((i * 7) % 4) * 0.025);
        wallMesh.setColorAt(i, colW.setRGB(sh, sh, sh + 0.02));
        m4.compose(vP.set(px, WALL_H + 0.04, pz), qI, vS.set(sx + 0.06, 0.08, sz + 0.06)); capMesh.setMatrixAt(i, m4);
        m4.compose(vP.set(px, 0.09, pz), qI, vS.set(sx + 0.08, 0.18, sz + 0.08)); baseMesh.setMatrixAt(i, m4);

        // Adiciona colunas estruturais nas extremidades de vigas longas
        if ((w >= 8 || h >= 8) && pi < MAXI - 2) {
          m4.compose(vP.set(px - sx / 2 + 0.15, WALL_H / 2 + 0.03, pz - sz / 2 + 0.15), qI, vS.set(0.38, WALL_H + 0.06, 0.38));
          pillarMesh.setMatrixAt(pi++, m4);
          m4.compose(vP.set(px + sx / 2 - 0.15, WALL_H / 2 + 0.03, pz + sz / 2 - 0.15), qI, vS.set(0.38, WALL_H + 0.06, 0.38));
          pillarMesh.setMatrixAt(pi++, m4);
        }

        const x0 = px - sx / 2 - 0.025, x1 = px + sx / 2 + 0.025, z0 = pz - sz / 2 - 0.025, z1 = pz + sz / 2 + 0.025, y = WALL_H + 0.085;
        edgeArr.set([x0, y, z0, x1, y, z0, x1, y, z0, x1, y, z1, x1, y, z1, x0, y, z1, x0, y, z1, x0, y, z0], i * 24);
      });

      wallMesh.count = capMesh.count = baseMesh.count = n;
      pillarMesh.count = pi;
      [wallMesh, capMesh, baseMesh, pillarMesh].forEach((m) => { m.instanceMatrix.needsUpdate = true; m.visible = m.count > 0; });
      if (wallMesh.instanceColor) wallMesh.instanceColor.needsUpdate = true;
      edgeGeo.setDrawRange(0, n * 8); edgeGeo.attributes.position.needsUpdate = true; edges.visible = n > 0;

      // Portais / Vergas superiores de portas detectadas pela VisÃ£o Computacional
      const doors = detectDoors();
      let li = 0;
      doors.forEach((d) => {
        if (li >= 500) return;
        const sx = d.w * CELL, sz = d.h * CELL;
        const px = (d.c + d.w / 2) * CELL - WW / 2, pz = (d.r + d.h / 2) * CELL - WH / 2;
        // Verga superior (acima da passagem dos operÃ¡rios, em y = 2.45m)
        m4.compose(vP.set(px, WALL_H - 0.18, pz), qI, vS.set(sx + 0.06, 0.22, sz + 0.06));
        lintelMesh.setMatrixAt(li++, m4);
        const stripeY = WALL_H - 0.055;
        m4.compose(vP.set(px, stripeY, pz), qI, vS.set(d.dir === 'h' ? sx + 0.08 : 0.08, 0.035, d.dir === 'v' ? sz + 0.08 : 0.08));
        lintelStripeMesh.setMatrixAt(li - 1, m4);
      });
      lintelMesh.count = lintelStripeMesh.count = li;
      lintelMesh.instanceMatrix.needsUpdate = true; lintelStripeMesh.instanceMatrix.needsUpdate = true;
      lintelMesh.visible = lintelStripeMesh.visible = li > 0;

      // Zonas de risco agrupadas com Greedy Meshing para visual limpo e zebrado
      const riskRects = greedyGrid(riskGrid);
      riskRects.forEach(([c, r, w, h], idx) => {
        const sx = w * CELL - 0.04, sz = h * CELL - 0.04;
        const px = (c + w / 2) * CELL - WW / 2, pz = (r + h / 2) * CELL - WH / 2;
        m4.compose(vP.set(px, 0.03, pz), qI, vS.set(sx, 1, sz));
        riskMesh.setMatrixAt(idx, m4);
      });
      riskMesh.count = riskRects.length; riskMesh.instanceMatrix.needsUpdate = true; riskMesh.visible = riskRects.length > 0;

      wallBoxes = n; pillarCount = pi; doorCount = doors.length; riskZonesCount = riskRects.length;
      updateWallAux();
      $('riskAux').textContent = 'â‰ˆ ' + f1(riskCount * CELL * CELL) + ' mÂ² Â· ' + riskZonesCount + ' zona(s)';
    }
  // =========================================================================
  // ===== 4. POOL DE AVATARES E TOTENS TÁCTICOS =====
  // =========================================================================

    // ---------- OperÃ¡rios (Layer 1 para CCTV + Totens na Layer 2 para Mapa 3D) ----------
    const SHIRT_HEX = 0x3b4552, VEST_HEX = 0xa3e635, VEST_EMISSIVE = 0x1f3a00, ALERT_RED = 0xef4444, ALERT_GLOW = 0xb91c1c;

    function makeLabel(text, color) {
      const c = document.createElement('canvas'); c.width = 160; c.height = 56;
      const g = c.getContext('2d');
      const draw = (txt) => {
        g.clearRect(0, 0, 160, 56);
        g.fillStyle = 'rgba(11,15,20,0.85)'; g.fillRect(0, 8, 160, 40);
        g.strokeStyle = '#34445a'; g.strokeRect(0.5, 8.5, 159, 39);
        g.fillStyle = color || '#f2b705'; g.font = '600 24px monospace'; g.textAlign = 'center'; g.textBaseline = 'middle';
        g.fillText(String(txt).slice(0, 10), 80, 29);
      };
      draw(text);
      const tex = new THREE.CanvasTexture(c);
      const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true }));
      sp.scale.set(2.2, 0.77, 1);
      sp.userData.redraw = (txt) => { draw(txt); tex.needsUpdate = true; };   // reaproveita a textura quando o rÃ³tulo muda
      return sp;
    }

    // Geometrias e materiais comuns sÃ£o criados UMA vez e compartilhados por todos os operÃ¡rios (menos memÃ³ria e menos draw setup).
    const GEO = {
      body: new THREE.CylinderGeometry(0.29, 0.29, 1.4, 20), vest: new THREE.CylinderGeometry(0.315, 0.315, 0.95, 20, 1, true),
      stripe: new THREE.CylinderGeometry(0.322, 0.322, 0.07, 20, 1, true), head: new THREE.SphereGeometry(0.2, 18, 14),
      hat: new THREE.SphereGeometry(0.28, 20, 14), blob: new THREE.CircleGeometry(0.42, 20),
    };
    const MAT = {
      stripe: new THREE.MeshStandardMaterial({ color: 0xe5e7eb, roughness: 0.3, emissive: 0x4b5563, side: THREE.DoubleSide }),
      head: new THREE.MeshStandardMaterial({ color: 0xe0b394, roughness: 0.75 }), hat: new THREE.MeshStandardMaterial({ color: 0xfacc15, roughness: 0.4 }),
      blob: new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.35, depthWrite: false }),
    };
    function makeWorker(i, riskBias) {
      const g = new THREE.Group(), inner = new THREE.Group();
      const shirtMat = new THREE.MeshStandardMaterial({ color: SHIRT_HEX, roughness: 0.7, metalness: 0.05, emissive: 0x000000 });
      const body = new THREE.Mesh(GEO.body, shirtMat);
      body.position.y = 0.7;

      const vestMat = new THREE.MeshStandardMaterial({ color: VEST_HEX, roughness: 0.5, metalness: 0.05, emissive: VEST_EMISSIVE, side: THREE.DoubleSide });
      const vest = new THREE.Mesh(GEO.vest, vestMat);
      vest.position.y = 0.88;
      [0.1, -0.2].forEach((y) => {
        const s = new THREE.Mesh(GEO.stripe, MAT.stripe);
        s.position.y = y; vest.add(s);
      });

      const head = new THREE.Mesh(GEO.head, MAT.head);
      head.position.y = 1.56;
      const hat = new THREE.Mesh(GEO.hat, MAT.hat);
      hat.position.y = 1.68;

      inner.add(body); inner.add(vest); inner.add(head); inner.add(hat);
      const blob = new THREE.Mesh(GEO.blob, MAT.blob);
      blob.rotation.x = -Math.PI / 2; blob.position.y = 0.03; g.add(blob);
      const name = 'OP-0' + (i + 1);
      const label = makeLabel(name); label.position.y = 2.55; label.visible = false;
      g.add(inner); g.add(label);
      inner.traverse((o) => { o.layers.set(1); o.castShadow = false; }); blob.layers.set(1);
      scene.add(g);
      return { slot: i, name, g, inner, label, shirtMat, vestMat, hat, vest, head, x: 0, z: 0, path: null, pi: 0, wait: 0.4, goingRisk: false,
               riskBias, inRisk: false, active: false, moving: false, invasions: 0, speed: 2.1 + i * 0.35,
               temCapacete: true, temColete: true, emInfracao: false,
               seenBy: [false, false, false], tracked: true, lastSeenT: 0, lastSeenX: 0, lastSeenZ: 0, tx: 0, tz: 0, identified: false, idNum: 101 + i, totem: null };
    }
    // Pool de avatares: a simulaÃ§Ã£o usa sÃ³ os 2 primeiros (SIM_N); no modo real cada trilha recebe um avatar livre do pool.
    const SIM_N = 2, POOL_N = 6;
    const workers = Array.from({ length: POOL_N }, (_, i) => makeWorker(i, i === 0 ? 0.6 : 0.4));
    let liveMode = false;                                  // true = sÃ³ dados reais (Arduino / WebSocket); a simulaÃ§Ã£o fica desligada

    function spawn(w) {
      if (liveMode || w.slot >= SIM_N) return;
      const list = freeList.length ? freeList : riskList;
      if (!list.length) { w.active = false; w.g.visible = false; return; }
      const idx = list[(Math.random() * list.length) | 0];
      w.x = cx(idx % COLS); w.z = cz((idx / COLS) | 0);
      w.path = null; w.wait = 0.3 + Math.random(); w.active = true; w.g.visible = true;
      w.inRisk = false; w.tracked = true; w.tx = w.x; w.tz = w.z; w.lastSeenX = w.x; w.lastSeenZ = w.z; w.lastSeenT = clock.elapsedTime; w.seenBy = [false, false, false];
      if (w.totem) { w.totem.pts.length = 0; w.totem.key = ''; }
      w.g.position.set(w.x, 0, w.z);
    }

    const DIRS = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]];
    const Q = new Int32Array(COLS * ROWS), PREV = new Int32Array(COLS * ROWS);
    function findPath(sc, sr, tc, tr) {
      const s = sr * COLS + sc, g = tr * COLS + tc;
      if (!pass[s] || !pass[g]) return null;
      PREV.fill(-2); PREV[s] = -1;
      let h = 0, t = 0; Q[t++] = s;
      while (h < t) {
        const cur = Q[h++];
        if (cur === g) break;
        const cc = cur % COLS, cr = (cur / COLS) | 0;
        for (let d = 0; d < 8; d++) {
          const nc = cc + DIRS[d][0], nr = cr + DIRS[d][1];
          if (nc < 0 || nr < 0 || nc >= COLS || nr >= ROWS) continue;
          const ni = nr * COLS + nc;
          if (PREV[ni] !== -2 || !pass[ni]) continue;
          if (DIRS[d][0] && DIRS[d][1] && (!pass[cr * COLS + nc] || !pass[nr * COLS + cc])) continue;
          PREV[ni] = cur; Q[t++] = ni;
        }
      }
      if (PREV[g] === -2) return null;
      const out = [];
      for (let n = g; n !== -1; n = PREV[n]) out.push({ x: cx(n % COLS), z: cz((n / COLS) | 0) });
      return out.reverse();
    }
    function nearestPassable(c, r) {
      for (let rad = 0; rad <= 3; rad++)
        for (let dr = -rad; dr <= rad; dr++)
          for (let dc = -rad; dc <= rad; dc++) {
            const rr = r + dr, cc = c + dc;
            if (rr >= 0 && cc >= 0 && rr < ROWS && cc < COLS && pass[rr * COLS + cc]) return [cc, rr];
          }
      return null;
    }
    function pickTarget(w) {
      const start = nearestPassable(toCol(w.x), toRow(w.z));
      if (!start) return false;
      for (let k = 0; k < 8; k++) {
        const goRisk = riskList.length > 0 && Math.random() < w.riskBias;
        const list = goRisk ? riskList : (freeList.length ? freeList : riskList);
        const idx = list[(Math.random() * list.length) | 0];
        const tc = idx % COLS, tr = (idx / COLS) | 0;
        if (k < 6 && Math.abs(tc - start[0]) + Math.abs(tr - start[1]) < 12) continue;
        const p = findPath(start[0], start[1], tc, tr);
        if (p && p.length > 1) { w.path = p; w.pi = 1; w.goingRisk = goRisk; return true; }
      }
      return false;
    }
    function stepWorker(w, dt, t) {
      if (!w.active) return;
      w.moving = false;
      if (w.wait > 0) { w.wait -= dt; }
      else {
        if (!w.path && !pickTarget(w)) w.wait = 1;
        else if (w.path) {
          const wp = w.path[w.pi];
          const dx = wp.x - w.x, dz = wp.z - w.z, dist = Math.hypot(dx, dz), step = w.speed * dt;
          w.moving = true;
          if (dist <= step) {
            w.x = wp.x; w.z = wp.z; w.pi++;
            if (w.pi >= w.path.length) { w.path = null; w.wait = w.goingRisk ? 2.4 : 0.6 + Math.random(); }
          } else { w.x += dx / dist * step; w.z += dz / dist * step; }
        }
      }
      w.g.position.set(w.x, 0, w.z);
      w.inner.position.y = w.moving ? Math.abs(Math.sin(t * 9 + w.speed)) * 0.07 : 0;
    }

    function goToRisk(w) {
      if (!w.active) return;
      if (!riskList.length) { logEvent('Sem cÃ©lula de risco navegÃ¡vel para ' + w.name + '.', 'alert'); return; }
      const start = nearestPassable(toCol(w.x), toRow(w.z));
      if (!start) return;
      let best = null;
      for (let k = 0; k < 10; k++) {
        const idx = riskList[(Math.random() * riskList.length) | 0];
        const p = findPath(start[0], start[1], idx % COLS, (idx / COLS) | 0);
        if (p && p.length > 1 && (!best || p.length < best.length)) best = p;
      }
      if (!best) { logEvent(w.name + ': nenhuma rota atÃ© a Ã¡rea de risco a partir daqui.', 'alert'); return; }
      w.path = best; w.pi = 1; w.goingRisk = true; w.wait = 0;
      logEvent(w.name + ' recebeu rota BFS atÃ© a Ã¡rea de risco (' + best.length + ' cÃ©lulas).');
    }

    function toggleEpi(w, kind) {
      const key = kind === 'cap' ? 'temCapacete' : 'temColete';
      const nome = kind === 'cap' ? 'Capacete' : 'Colete';
      w[key] = !w[key];
      if (w[key]) logEvent(w.name + ' recolocou o ' + nome + '.', 'ok');
      else logEvent(w.name + ' removeu o ' + nome + ' (sem EPI).', 'alert');
      refreshUI();
    }

    const chipsEl = $('workers');
    workers.forEach((w) => {
      const el = document.createElement('div');
      el.className = 'wchip'; el.dataset.alert = '0';
      el.innerHTML =
        '<div class="top2"><span class="name"></span><span class="pill">Em rota</span></div>' +
        '<div class="xy"></div><div class="inv"></div>' +
        '<div class="wbtns">' +
        '<button type="button" class="btn wbtn" data-act="cap"></button>' +
        '<button type="button" class="btn wbtn" data-act="vest"></button>' +
        '<button type="button" class="btn wbtn" data-act="risk">Ir p/ Risco</button>' +
        '</div>';
      el.querySelector('.name').textContent = w.name;
      chipsEl.appendChild(el); w.el = el;
      w.nodes = {
        name: el.querySelector('.name'), pill: el.querySelector('.pill'), xy: el.querySelector('.xy'), inv: el.querySelector('.inv'),
        cap: el.querySelector('[data-act="cap"]'), vest: el.querySelector('[data-act="vest"]'), risk: el.querySelector('[data-act="risk"]'),
      };
      w.nodes.cap.addEventListener('click', () => toggleEpi(w, 'cap'));
      w.nodes.vest.addEventListener('click', () => toggleEpi(w, 'vest'));
      w.nodes.risk.addEventListener('click', () => goToRisk(w));
    });

    const setText = (n, v) => { if (n.textContent !== v) n.textContent = v; };
    const setAttr = (n, k, v) => { if (n.getAttribute(k) !== v) n.setAttribute(k, v); };

    let totalPessoaFrames = 0, conformesPessoaFrames = 0, sampleAcc = 0;
    function sampleConformity(dt) {
      sampleAcc += dt;
      while (sampleAcc >= SAMPLE_DT) {
        sampleAcc -= SAMPLE_DT;
        workers.forEach((w) => {
          if (!w.active || !w.tracked) return;
          totalPessoaFrames++;
          if (w.temCapacete && w.temColete && !w.inRisk) conformesPessoaFrames++;
        });
      }
    }
    function renderConformity() {
      const card = $('confCard');
      if (!totalPessoaFrames) {
        setAttr(card, 'data-state', 'none');
        setText($('confVal'), 'â€”'); setText($('confStatus'), 'Aguardando amostras');
        $('confFill').style.width = '0%';
        setText($('confAux'), 'Meta do TCC: ' + META + '% Â· 0 pessoas-frame');
        return;
      }
      const pct = conformesPessoaFrames / totalPessoaFrames * 100;
      const ok = pct >= META, warn = !ok && pct >= 85;
      setAttr(card, 'data-state', ok ? 'ok' : warn ? 'warn' : 'bad');
      setText($('confVal'), f1(pct) + '%');
      setText($('confStatus'), ok ? 'âœ“ Dentro da meta' : 'â–¼ Abaixo da meta (' + f1(pct - META) + ' p.p.)');
      $('confFill').style.width = pct.toFixed(1) + '%';
      setText($('confAux'), fmt(conformesPessoaFrames) + ' de ' + fmt(totalPessoaFrames) + ' pessoas-frame conformes Â· meta ' + META + '%');
    }
    $('confReset').addEventListener('click', () => {
      totalPessoaFrames = 0; conformesPessoaFrames = 0; sampleAcc = 0;
      logEvent('Contagem de conformidade reiniciada.');
      renderConformity();
    });

    const describe = (w) => {
      const parts = [];
      if (!w.temCapacete) parts.push('sem Capacete');
      if (!w.temColete) parts.push('sem Colete');
      if (w.inRisk) parts.push('invadiu Ãrea de Risco');
      return w.name + ' ' + parts.join(' + ');
    };

    function refreshUI() {
      const bad = [];
      workers.forEach((w) => {
        const emInfracao = w.inRisk || !w.temCapacete || !w.temColete;
        w.emInfracao = emInfracao;
        const n = w.nodes;
        const oculto = w.slot >= SIM_N && !w.active;               // vagas do pool sÃ³ aparecem quando ocupadas
        if (w.el.hidden !== oculto) w.el.hidden = oculto;
        if (w.cn && w.cn.li.hidden !== oculto) w.cn.li.hidden = oculto;
        setText(n.name, w.identified && !liveMode ? w.name + ' Â· ID #' + w.idNum : w.name);
        setText(n.cap, 'Capacete: ' + (w.capKnown === false ? '?' : w.temCapacete ? 'OK' : 'SEM'));
        setText(n.vest, 'Colete: ' + (w.vestKnown === false ? '?' : w.temColete ? 'OK' : 'SEM'));
        setAttr(n.cap, 'data-off', w.temCapacete ? '0' : '1');
        setAttr(n.vest, 'data-off', w.temColete ? '0' : '1');
        const noRisk = !w.active || !riskList.length;
        if (n.risk.disabled !== noRisk) n.risk.disabled = noRisk;

        if (!w.active) {
          setText(n.pill, liveMode ? 'Livre' : 'Sem rota'); setText(n.xy, liveMode ? 'aguardando trilha real' : 'sem Ã¡rea navegÃ¡vel'); setText(n.inv, '');
          setAttr(w.el, 'data-alert', '0');
          return;
        }
        setAttr(w.el, 'data-alert', emInfracao ? '1' : '0');
        const semEpi = !w.temCapacete || !w.temColete;
        setText(n.pill, !w.tracked ? 'SEM SINAL' : w.inRisk && semEpi ? 'INFRAÃ‡ÃƒO' : w.inRisk ? 'INVASÃƒO' : semEpi ? 'SEM EPI' : (w.moving ? 'Em rota' : 'Parado'));
        setText(n.xy, (liveMode ? 'real Â· ' : '') + 'X ' + f1(w.tx) + ' Â· Z ' + f1(w.tz) + ' m' + (w.tracked ? '' : ' Â· Ãºltima posiÃ§Ã£o'));
        setText(n.inv, 'invasÃµes: ' + w.invasions);
        if (emInfracao && w.tracked) bad.push(w);
      });

      if (liveMode && !workers.some((w) => w.active)) {
        const fe = fonte.estado(), ok = fe.estado === 'ativa';
        setBanner(ok ? 'ok' : 'idle', ok ? 'Dados reais ativos. Nenhum trabalhador na cena.' : 'Sem dados reais do Arduino',
          ok ? 'Fonte: ' + (fe.canal === 'painel' ? 'Arduino (conexÃ£o do painel)' : fe.url) + (semPosicao ? ' Â· ' + semPosicao + ' trilha(s) sem posiÃ§Ã£o na planta (calibraÃ§Ã£o pendente)' : '') : (fe.rotulo || 'Escolha uma fonte de dados.') + '. Nenhum dado simulado estÃ¡ sendo exibido.');
      } else if (!workers.some((w) => w.active)) {
        setBanner('idle', 'Nenhuma Ã¡rea navegÃ¡vel encontrada na planta', 'Abra passagens entre as paredes ou carregue outra planta.');
      } else if (bad.length) {
        setBanner('alert', 'ALERTA CRÃTICO: ' + bad.map(describe).join(' Â· ') + '!',
          bad.map((w) => w.name + ' em X ' + f1(w.tx) + ' Â· Z ' + f1(w.tz) + ' m').join('   |   '));
      } else {
        setBanner('ok', 'Monitoramento ativo. Nenhuma infraÃ§Ã£o de EPI ou de Ã¡rea de risco.', fmt(riskCount) + ' cÃ©lulas de risco vigiadas em ' + f1(riskCount * CELL * CELL) + ' mÂ².');
      }
      renderConformity();
    }

    // ---------- Telemetria Industrial: Totens TÃ¡ticos + Billboards 2D ----------
    const TOT = { ok: '#3ccf7e', bad: '#ef4444', lost: '#8a96a3' };
    const BREAD = 14;
    function drawHelmet(g, cx, cy, sz) {
      g.save(); g.translate(cx, cy); g.scale(sz / 80, sz / 80);
      g.fillStyle = '#facc15'; g.strokeStyle = '#3a2e00'; g.lineWidth = 3;
      g.beginPath(); g.arc(0, 6, 30, Math.PI, 0); g.closePath(); g.fill(); g.stroke();
      g.fillRect(-38, 6, 76, 9); g.strokeRect(-38, 6, 76, 9);
      g.fillStyle = '#d4a90a'; g.fillRect(-5, -24, 10, 30);
      g.restore();
    }
    function drawVest(g, cx, cy, sz) {
      g.save(); g.translate(cx, cy); g.scale(sz / 80, sz / 80);
      g.fillStyle = '#a3e635'; g.strokeStyle = '#1f3a00'; g.lineWidth = 3;
      g.beginPath(); g.moveTo(-24, -32); g.lineTo(-8, -32); g.lineTo(0, -16); g.lineTo(8, -32); g.lineTo(24, -32); g.lineTo(30, 30); g.lineTo(-30, 30); g.closePath(); g.fill(); g.stroke();
      g.fillStyle = '#e5e7eb'; g.fillRect(-29, 2, 58, 7); g.fillRect(-29, 16, 58, 7);
      g.restore();
    }
    function drawFloor(g, cx, cy, sz) {
      g.save(); g.translate(cx, cy); g.scale(sz / 80, sz / 80);
      g.beginPath(); g.moveTo(-26, -18); g.lineTo(38, -18); g.lineTo(26, 22); g.lineTo(-38, 22); g.closePath();
      g.fillStyle = '#facc15'; g.fill(); g.save(); g.clip();
      g.strokeStyle = '#1b1b1b'; g.lineWidth = 9;
      for (let k = -60; k < 80; k += 22) { g.beginPath(); g.moveTo(k, 30); g.lineTo(k + 30, -30); g.stroke(); }
      g.restore(); g.strokeStyle = '#3a2e00'; g.lineWidth = 3;
      g.beginPath(); g.moveTo(-26, -18); g.lineTo(38, -18); g.lineTo(26, 22); g.lineTo(-38, 22); g.closePath(); g.stroke();
      g.restore();
    }
    function slash(g, cx, cy, sz) {
      g.save(); g.lineCap = 'round';
      g.strokeStyle = '#1a0000'; g.lineWidth = sz * 0.15; g.beginPath(); g.moveTo(cx - sz * 0.46, cy - sz * 0.46); g.lineTo(cx + sz * 0.46, cy + sz * 0.46); g.stroke();
      g.strokeStyle = '#ff2d2d'; g.lineWidth = sz * 0.09; g.beginPath(); g.moveTo(cx - sz * 0.46, cy - sz * 0.46); g.lineTo(cx + sz * 0.46, cy + sz * 0.46); g.stroke();
      g.restore();
    }
    function makeTotem(w) {
      const tg = new THREE.Group();
      const wIndex = Math.max(0, workers.indexOf(w));
      const mk = (geo, color, op) => new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: op, side: THREE.DoubleSide, depthWrite: false }));
      const base = mk(new THREE.CircleGeometry(0.68, 32), 0x05080c, 0.75); base.rotation.x = -Math.PI / 2; base.position.y = 0.05;
      const ring = mk(new THREE.RingGeometry(0.42, 0.62, 40), 0x3ccf7e, 0.98); ring.rotation.x = -Math.PI / 2; ring.position.y = 0.055;
      const dot = mk(new THREE.CircleGeometry(0.20, 24), 0x3ccf7e, 1); dot.rotation.x = -Math.PI / 2; dot.position.y = 0.06;
      const aura = mk(new THREE.CylinderGeometry(0.16, 0.28, 2.0, 16), 0x3ccf7e, 0.22); aura.position.y = 1.05;
      const pole = mk(new THREE.CylinderGeometry(0.045, 0.045, 2.2, 12), 0x3ccf7e, 0.98); pole.position.y = 1.15;
      const diamond = mk(new THREE.OctahedronGeometry(0.24, 0), 0x3ccf7e, 1); diamond.position.y = 1.15;
      const rp = []; for (let k = 0; k <= 40; k++) { const a = k / 40 * Math.PI * 2; rp.push(new THREE.Vector3(Math.cos(a) * 0.62, 0.065, Math.sin(a) * 0.62)); }
      const lostRing = new THREE.Line(new THREE.BufferGeometry().setFromPoints(rp), new THREE.LineDashedMaterial({ color: 0x8a96a3, dashSize: 0.14, gapSize: 0.1, transparent: true, opacity: 0.9 }));
      lostRing.computeLineDistances();
      const lostPole = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0.06, 0), new THREE.Vector3(0, 2.2, 0)]), new THREE.LineDashedMaterial({ color: 0x8a96a3, dashSize: 0.12, gapSize: 0.09, transparent: true, opacity: 0.9 }));
      lostPole.computeLineDistances();
      lostRing.visible = false; lostPole.visible = false;
      tg.add(base, ring, dot, aura, pole, diamond, lostRing, lostPole);
      const trail = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0x3ccf7e, transparent: true, opacity: 0.9 }));
      trail.geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(BREAD * 3), 3));
      trail.geometry.setDrawRange(0, 0); trail.frustumCulled = false;
      const cv = document.createElement('canvas'); cv.width = 512; cv.height = 320;
      const tex = new THREE.CanvasTexture(cv); tex.anisotropy = 4;
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false, depthWrite: false }));
      sprite.center.set(0.5, 0); sprite.scale.set(5.4, 3.3, 1); sprite.position.y = 2.35 + wIndex * 0.35; sprite.renderOrder = 20 + wIndex;
      tg.add(sprite);
      [tg, base, ring, dot, aura, pole, diamond, lostRing, lostPole, sprite].forEach((o) => o.layers.set(2)); trail.layers.set(2);
      scene.add(tg); scene.add(trail);
      return { tg, base, ring, dot, aura, pole, diamond, lostRing, lostPole, trail, sprite, cv, g: cv.getContext('2d'), tex, pts: [], key: '' };
    }
    function paintCard(w, tt, state, blink, lostSec) {
      const T = w.totem, g = T.g; g.clearRect(0, 0, 512, 320);
      g.textAlign = 'center'; g.textBaseline = 'middle'; g.lineJoin = 'round';
      g.shadowColor = 'rgba(0,0,0,0.85)'; g.shadowBlur = 14; g.shadowOffsetY = 5;
      const mono = '"IBM Plex Mono", ui-monospace, monospace';
      const nm = w.identified ? w.name : w.name;
      const id = w.identified ? w.idNum : '---';
      const pointer = (color, y) => { g.fillStyle = color; g.beginPath(); g.moveTo(240, y); g.lineTo(272, y); g.lineTo(256, y + 13); g.closePath(); g.fill(); };
      if (state === 'ok') {
        const x = 36, y = 136, W = 440, H = 164;
        g.fillStyle = 'rgba(8,14,20,0.96)'; g.fillRect(x, y, W, H);
        g.shadowColor = 'transparent'; g.shadowBlur = 0;
        g.strokeStyle = '#0d5e36'; g.lineWidth = 9; g.strokeRect(x + 2, y + 2, W - 4, H - 4);
        g.strokeStyle = '#3ccf7e'; g.lineWidth = 5; g.strokeRect(x + 9, y + 9, W - 18, H - 18);
        g.fillStyle = '#17803d'; g.fillRect(x + 12, y + 12, W - 24, 38);
        g.fillStyle = '#ffffff'; g.font = '800 19px ' + mono; g.fillText('â— RASTREIO ATIVO    ID #' + id, 256, y + 31);
        g.textAlign = 'left'; g.fillStyle = '#f2fff7'; g.font = '900 46px ' + mono; g.fillText(nm, x + 28, y + 96);
        g.fillStyle = '#9bf3bd'; g.font = '700 17px ' + mono; g.fillText('EPI VALIDADO', x + 31, y + 126);
        [364, 430].forEach((cx) => { g.fillStyle = '#07110b'; g.beginPath(); g.arc(cx, y + 94, 37, 0, Math.PI * 2); g.fill(); g.strokeStyle = '#3ccf7e'; g.lineWidth = 2; g.stroke(); });
        drawHelmet(g, 364, y + 94, 58); drawVest(g, 430, y + 94, 58);
        g.fillStyle = '#17803d'; g.fillRect(354, y + 132, 86, 24);
        g.fillStyle = '#ffffff'; g.textAlign = 'center'; g.font = '900 17px ' + mono; g.fillText('âœ“ OK', 397, y + 144);
        pointer('#3ccf7e', y + H - 2);
      } else if (state === 'lost') {
        const x = 36, y = 128, W = 440, H = 174;
        g.fillStyle = 'rgba(18,23,30,0.95)'; g.fillRect(x, y, W, H);
        g.shadowColor = 'transparent'; g.shadowBlur = 0;
        g.setLineDash([15, 9]); g.strokeStyle = '#cbd5e1'; g.lineWidth = 5; g.strokeRect(x + 4, y + 4, W - 8, H - 8); g.setLineDash([]);
        g.fillStyle = '#0f7490'; g.fillRect(x + 12, y + 12, W - 24, 36);
        g.fillStyle = '#ecfeff'; g.font = '800 20px ' + mono; g.fillText('â—Œ ÃšLTIMA POSIÃ‡ÃƒO CONHECIDA', 256, y + 30);
        g.fillStyle = '#f1f5f9'; g.font = '900 37px ' + mono; g.fillText(nm, 256, y + 87);
        g.fillStyle = '#cbd5e1'; g.font = '800 22px ' + mono; g.fillText('SINAL PERDIDO  Â·  ID #' + id, 256, y + 120);
        g.fillStyle = '#facc15'; g.font = '700 19px ' + mono; g.fillText('hÃ¡ ' + lostSec + ' s sem atualizaÃ§Ã£o', 256, y + 151);
        pointer('#cbd5e1', y + H - 1);
      } else {
        const x = 20, y = 12, W = 472, H = 296;
        g.fillStyle = 'rgba(32,4,8,0.97)'; g.fillRect(x, y, W, H);
        g.shadowColor = 'transparent'; g.shadowBlur = 0;
        g.strokeStyle = '#020305'; g.lineWidth = 12; g.strokeRect(x + 5, y + 5, W - 10, H - 10);
        g.strokeStyle = blink ? '#facc15' : '#ef4444'; g.lineWidth = 8; g.strokeRect(x + 15, y + 15, W - 30, H - 30);
        g.fillStyle = '#b91c1c'; g.fillRect(x + 20, y + 20, W - 40, 52);
        g.fillStyle = '#ffffff'; g.font = '900 25px ' + mono; g.fillText('âš  ALERTA DE INFRAÃ‡ÃƒO', 256, y + 46);
        g.fillStyle = '#ffe4e6'; g.font = '900 32px ' + mono; g.fillText(nm + '  Â·  ID #' + id, 256, y + 100);
        const items = [];
        if (!w.temCapacete) items.push(['SEM CAPACETE', (c, cx, cy) => { drawHelmet(c, cx, cy, 72); slash(c, cx, cy, 76); }]);
        if (!w.temColete) items.push(['SEM COLETE', (c, cx, cy) => { drawVest(c, cx, cy, 72); slash(c, cx, cy, 76); }]);
        if (w.inRisk) items.push(['ÃREA PROIBIDA', (c, cx, cy) => { drawFloor(c, cx, cy, 72); slash(c, cx, cy, 76); }]);
        const step = 118, start = 256 - ((items.length - 1) * step) / 2;
        items.forEach((it, k) => {
          const cx = start + k * step, cy = y + 177;
          g.fillStyle = '#080b10'; g.beginPath(); g.arc(cx, cy, 48, 0, Math.PI * 2); g.fill();
          g.strokeStyle = '#ef4444'; g.lineWidth = 3; g.stroke(); it[1](g, cx, cy);
          g.fillStyle = '#fecaca'; g.font = '800 15px ' + mono; g.fillText(it[0], cx, y + 244);
        });
        g.fillStyle = blink ? '#facc15' : '#ef4444'; g.font = '800 17px ' + mono; g.fillText('AÃ‡ÃƒO IMEDIATA NECESSÃRIA', 256, y + 273);
        pointer('#ef4444', y + H - 1);
      }
      T.tex.needsUpdate = true;
    }
    function setTotemColor(T, hex, op) {
      [T.ring, T.dot, T.pole].forEach((m) => { m.material.color.set(hex); m.material.opacity = op; });
      T.trail.material.color.set(hex);
    }
    function updateTotems(t, blink) {
      workers.forEach((w) => {
        if (!w.totem) w.totem = makeTotem(w);
        const T = w.totem, on = w.active;
        T.tg.visible = on; T.trail.visible = on;
        if (!on) return;
        if (w.tracked) { w.tx = w.x; w.tz = w.z; }
        T.tg.position.set(w.tx, 0, w.tz);
        const lp = T.pts[T.pts.length - 1];
        if (w.tracked && (!lp || Math.hypot(lp[0] - w.tx, lp[1] - w.tz) > 0.35)) { T.pts.push([w.tx, w.tz]); if (T.pts.length > BREAD) T.pts.shift(); }
        else if (!w.tracked && lp && (lp[0] !== w.tx || lp[1] !== w.tz) && Math.hypot(lp[0] - w.tx, lp[1] - w.tz) > 1.5) T.pts.length = 0;
        const arr = T.trail.geometry.attributes.position.array;
        T.pts.forEach((q, k) => { arr[k * 3] = q[0]; arr[k * 3 + 1] = 0.04; arr[k * 3 + 2] = q[1]; });
        if (w.tracked && T.pts.length) { const k = T.pts.length; if (k < BREAD) { arr[k * 3] = w.tx; arr[k * 3 + 1] = 0.04; arr[k * 3 + 2] = w.tz; } }
        T.trail.geometry.setDrawRange(0, Math.min(BREAD, T.pts.length + (w.tracked && T.pts.length < BREAD ? 1 : 0)));
        T.trail.geometry.attributes.position.needsUpdate = true;
        const state = !w.tracked ? 'lost' : w.emInfracao ? 'bad' : 'ok';
        const lostSec = Math.max(0, Math.floor(t - w.lastSeenT));
        const bl = state === 'bad' ? (blink ? 1 : 0) : 0;
        const key = state + '|' + w.identified + '|' + w.temCapacete + w.temColete + w.inRisk + '|' + bl + '|' + (state === 'lost' ? lostSec : 0);
        if (key !== T.key) { T.key = key; paintCard(w, t, state, blink, lostSec); }
        const lost = state === 'lost';
        T.lostRing.visible = lost; T.lostPole.visible = lost;
        [T.ring, T.dot, T.aura, T.pole, T.diamond].forEach((m) => m.visible = !lost);
        T.diamond.rotation.y = t * 2.2;
        T.aura.scale.set(1, 1 + 0.06 * Math.sin(t * 2.7), 1);
        if (state === 'ok') {
          setTotemColor(T, 0x3ccf7e, 0.98);
          T.aura.material.color.setHex(0x3ccf7e); T.aura.material.opacity = 0.22;
          T.diamond.material.color.setHex(0x3ccf7e); T.diamond.material.opacity = 1;
          T.dot.material.opacity = 1;
        } else if (state === 'bad') {
          setTotemColor(T, 0xef4444, blink ? 1 : 0.7);
          T.aura.material.color.setHex(0xef4444); T.aura.material.opacity = blink ? 0.34 : 0.22;
          T.diamond.material.color.setHex(0xfacc15); T.diamond.material.opacity = 1;
          const sc = 1 + 0.18 * Math.sin(t * 8); T.ring.scale.set(sc, sc, 1); T.diamond.scale.setScalar(1 + 0.16 * Math.sin(t * 8));
        } else {
          setTotemColor(T, 0x8a96a3, 0.45);
          T.dot.material.opacity = 0.5;
        }
        if (state !== 'bad') { T.ring.scale.set(1, 1, 1); T.diamond.scale.setScalar(1); }
      });
    }
  // =========================================================================
  // ===== 5. CÂMERAS PTZ E MONITOR CCTV =====
  // =========================================================================

    // ---------- CÃ¢meras de SeguranÃ§a + Monitor CCTV ----------
    let mainW = 1, mainH = 1;
    const rigs = CAMS.map((def) => {
      const tgt = new THREE.Vector3(def.target[0], def.target[1], def.target[2]);
      const cam = new THREE.PerspectiveCamera(def.fov, 4 / 3, 0.2, 120);
      cam.position.set(def.pos[0], def.pos[1], def.pos[2]);
      cam.lookAt(tgt); cam.updateMatrixWorld(true); cam.matrixWorldInverse.copy(cam.matrixWorld).invert(); cam.layers.enable(1);

      const grp = new THREE.Group();
      grp.position.copy(cam.position); grp.lookAt(tgt);
      const darkMat = new THREE.MeshStandardMaterial({ color: 0x1d242d, roughness: 0.5, metalness: 0.4 });
      const lensGeo = new THREE.CylinderGeometry(0.1, 0.13, 0.22, 16); lensGeo.rotateX(Math.PI / 2);
      const lens = new THREE.Mesh(lensGeo, new THREE.MeshStandardMaterial({ color: 0x05080c, roughness: 0.2, metalness: 0.8 }));
      lens.position.z = 0.4;
      const ledMat = new THREE.MeshBasicMaterial({ color: 0xff3b3b });
      const led = new THREE.Mesh(new THREE.SphereGeometry(0.04, 8, 8), ledMat); led.position.set(0.15, 0.1, 0.31);
      grp.add(new THREE.Mesh(new THREE.BoxGeometry(0.46, 0.3, 0.6), darkMat)); grp.add(lens); grp.add(led);
      scene.add(grp);
      const wallV = new THREE.Vector3(def.wall[0], 0, def.wall[1]).normalize();
      const plate = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.55, 0.06), darkMat);
      plate.position.copy(cam.position).addScaledVector(wallV, 0.36); plate.lookAt(plate.position.clone().sub(wallV));
      const arm = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.12, 0.3), darkMat);
      arm.position.copy(cam.position).addScaledVector(wallV, 0.2); arm.lookAt(arm.position.clone().sub(wallV));
      scene.add(plate); scene.add(arm);
      const label = makeLabel(def.name, '#b6ff3b'); label.scale.set(1.6, 0.56, 1);
      label.position.copy(cam.position); label.position.y += 0.75; scene.add(label);

      const d = cam.position.distanceTo(tgt) * 1.15, th = Math.tan(THREE.MathUtils.degToRad(def.fov / 2)), tw = th * cam.aspect;
      const c4 = [[-tw, -th], [tw, -th], [tw, th], [-tw, th]].map(([a, b]) => new THREE.Vector3(a * d, b * d, -d));
      const ap = new THREE.Vector3(), tri = [], ln = [];
      for (let k = 0; k < 4; k++) { const a = c4[k], b = c4[(k + 1) % 4]; tri.push(ap.x, ap.y, ap.z, a.x, a.y, a.z, b.x, b.y, b.z); ln.push(ap.x, ap.y, ap.z, a.x, a.y, a.z, a.x, a.y, a.z, b.x, b.y, b.z); }
      [0, 1, 2, 0, 2, 3].forEach((k) => tri.push(c4[k].x, c4[k].y, c4[k].z));
      const fg = new THREE.BufferGeometry(); fg.setAttribute('position', new THREE.Float32BufferAttribute(tri, 3));
      const lg = new THREE.BufferGeometry(); lg.setAttribute('position', new THREE.Float32BufferAttribute(ln, 3));
      const fov = new THREE.Group();
      fov.add(new THREE.Mesh(fg, new THREE.MeshBasicMaterial({ color: 0xb6ff3b, transparent: true, opacity: 0.1, side: THREE.DoubleSide, depthWrite: false })));
      fov.add(new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ color: 0xb6ff3b, transparent: true, opacity: 0.6 })));
      fov.visible = false; fov.position.copy(cam.position); fov.quaternion.copy(cam.quaternion); scene.add(fov);
      const dv = tgt.clone().sub(cam.position), hz = Math.hypot(dv.x, dv.z);
      return { def, cam, grp, ledMat, plate, arm, label, fov, ptz: !!def.ptz, yaw0: Math.atan2(dv.z, dv.x), pitch0: Math.atan2(dv.y, hz),
               yaw: Math.atan2(dv.z, dv.x), pitch: Math.atan2(dv.y, hz), phase: def.id === '2A' ? 2.1 : 0, lockW: null, lockT: 0 };
    });

    function autoPlaceCams() {
      if (!planBounds) return;
      const pad = Math.max(1, Math.min(3, Math.floor(Math.min(planBounds.maxCol - planBounds.minCol, planBounds.maxRow - planBounds.minRow) / 6)));
      const minC = Math.min(planBounds.maxCol, planBounds.minCol + pad), maxC = Math.max(planBounds.minCol, planBounds.maxCol - pad);
      const minR = Math.min(planBounds.maxRow, planBounds.minRow + pad), maxR = Math.max(planBounds.minRow, planBounds.maxRow - pad);
      const center = [cx((planBounds.minCol + planBounds.maxCol) / 2), 0, cz((planBounds.minRow + planBounds.maxRow) / 2)];
      const slots = [[minC, minR, [0, -1]], [maxC, minR, [1, 0]], [minC, maxR, [-1, 1]]];
      rigs.forEach((r, i) => {
        const slot = slots[i], pos = [cx(slot[0]), 2.45, cz(slot[1])], def = CAMS[i];
        def.pos = pos; def.target = center.slice(); def.wall = slot[2];
        r.cam.position.set(pos[0], pos[1], pos[2]);
        const dx = center[0] - pos[0], dz = center[2] - pos[2], hz = Math.hypot(dx, dz);
        r.yaw0 = r.yaw = Math.atan2(dz, dx); r.pitch0 = r.pitch = Math.atan2(1.0 - pos[1], hz);
        r.cam.lookAt(center[0], center[1], center[2]); r.cam.updateMatrixWorld(true); r.cam.matrixWorldInverse.copy(r.cam.matrixWorld).invert();
        r.grp.position.copy(r.cam.position); r.grp.lookAt(center[0], center[1], center[2]);
        const wallV = new THREE.Vector3(slot[2][0], 0, slot[2][1]).normalize();
        r.plate.position.copy(r.cam.position).addScaledVector(wallV, 0.36); r.plate.lookAt(r.plate.position.clone().sub(wallV));
        r.arm.position.copy(r.cam.position).addScaledVector(wallV, 0.2); r.arm.lookAt(r.arm.position.clone().sub(wallV));
        r.label.position.copy(r.cam.position); r.label.position.y += 0.75;
        r.fov.position.copy(r.cam.position); r.fov.quaternion.copy(r.cam.quaternion);
        camYaw[i] = r.yaw;
      });
      drawCamLayer(); setCam(activeCam, true);
    }

    const blindEl = $('blind'), vp = new THREE.Vector3();
    function visibleToCam(cam, x, z) {
      vp.set(x, 1.0, z).applyMatrix4(cam.matrixWorldInverse);
      if (vp.z > -0.25) return false;
      vp.applyMatrix4(cam.projectionMatrix);
      if (Math.abs(vp.x) > 0.96 || Math.abs(vp.y) > 0.96) return false;
      return clearSight(cam, x, 1.0, z) || clearSight(cam, x, 1.75, z);
    }
    function updateTracking(t) {
      workers.forEach((w) => {
        if (!w.active) return;
        let any = false;
        rigs.forEach((r, i) => { w.seenBy[i] = visibleToCam(r.cam, w.x, w.z); if (w.seenBy[i]) any = true; });
        if (liveMode) { w.tracked = true; w.lastSeenT = t; w.identified = false; return; }   // real: a trilha vem do detector, sem ArUco nem ponto cego simulados
        if (!blindEl.checked) { w.tracked = true; w.lastSeenT = t; return; }
        if (any) {
          w.lastSeenT = t;
          if (!w.tracked) { w.tracked = true; w.tx = w.x; w.tz = w.z; logEvent(w.name + ' reencontrado â€” rastreio ao vivo retomado.', 'ok'); }
        } else if (w.tracked) {
          w.tracked = false; w.tx = w.x; w.tz = w.z;
          logEvent(w.name + ' saiu do FOV das cÃ¢meras â€” SINAL PERDIDO (Ãºltima posiÃ§Ã£o X ' + f1(w.tx) + ' Â· Z ' + f1(w.tz) + ').', 'alert');
        }
        if (w.seenBy[0] && !w.identified) {
          w.identified = true;
          logEvent(w.name + ' identificado na CAM 1A (ArUco #' + w.idNum + ').', 'ok');
        }
      });
    }
    const angDiff = (a, b) => Math.atan2(Math.sin(b - a), Math.cos(b - a));
    let planAcc = 0;
    function aim(r) {
      const cp = Math.cos(r.pitch);
      const tgt = new THREE.Vector3(r.cam.position.x + cp * Math.cos(r.yaw), r.cam.position.y + Math.sin(r.pitch), r.cam.position.z + cp * Math.sin(r.yaw));
      r.cam.lookAt(tgt); r.cam.updateMatrixWorld(true); r.cam.matrixWorldInverse.copy(r.cam.matrixWorld).invert();
      r.grp.lookAt(tgt);
      r.fov.position.copy(r.cam.position); r.fov.quaternion.copy(r.cam.quaternion);
    }
    function updatePTZ(t, dt) {
      let moved = false;
      rigs.forEach((r, i) => {
        if (!r.ptz) return;
        // PTZ FREEZE: cÃ¢mera ativa em ediÃ§Ã£o (pintura ou calibraÃ§Ã£o) mantÃ©m yaw/pitch exatos
        if (i === activeCam && (paint.on || calibState.on)) { r.frozen = true; return; }
        if (r.frozen) {                                   // retomada sem salto: a fase da varredura continua do Ã¢ngulo atual
          r.frozen = false; r.lockT = t;
          const q = Math.max(-1, Math.min(1, (r.yaw - r.yaw0) / THREE.MathUtils.degToRad(28)));
          r.phase = Math.asin(q) - t * 0.45;
        }
        let lock = null, best = 1e9;
        workers.forEach((w) => {
          if (!w.active || !w.emInfracao || !w.seenBy[i]) return;
          const d = Math.hypot(w.x - r.cam.position.x, w.z - r.cam.position.z);
          if (d < best) { best = d; lock = w; }
        });
        if (lock) { r.lockT = t; if (r.lockW !== lock) { r.lockW = lock; logEvent(r.def.name + ' travou mira em ' + lock.name + ' (infraÃ§Ã£o).', 'alert'); } }
        else if (r.lockW && t - r.lockT > 0.8) { logEvent(r.def.name + ' liberou a mira â€” varredura retomada.', 'ok'); r.lockW = null; }
        let ty, tp;
        if (r.lockW) {
          const dx = r.lockW.x - r.cam.position.x, dz = r.lockW.z - r.cam.position.z;
          ty = Math.atan2(dz, dx); tp = Math.atan2(1.0 - r.cam.position.y, Math.hypot(dx, dz));
        } else {
          ty = r.yaw0 + THREE.MathUtils.degToRad(28) * Math.sin(t * 0.45 + r.phase); tp = r.pitch0;
        }
        const k = 1 - Math.exp(-(r.lockW ? 5 : 3) * dt);
        r.yaw += angDiff(r.yaw, ty) * k; r.pitch += (tp - r.pitch) * k;
        aim(r); camYaw[i] = r.yaw; moved = true;
      });
      planAcc += dt;
      if (moved && planAcc > 0.1) { planAcc = 0; drawCamLayer(); }
    }

    function onCamChange() {
      rigs.forEach((r, i) => {
        const on = i === activeCam;
        r.fov.visible = on; r.ledMat.color.setHex(on ? 0xb6ff3b : 0xff3b3b); r.label.material.opacity = on ? 1 : 0.5;
      });
      if (calibState.on) setCalib(false);
      hover = null; drawBoxes(lastT);
    }

    const listEl = $('cctvList');
    workers.forEach((w) => {
      const li = document.createElement('li');
      const nm = document.createElement('b'), vis = document.createElement('span'), cap = document.createElement('span'), vst = document.createElement('span');
      nm.textContent = w.name; li.append(nm, vis, cap, vst); listEl.appendChild(li);
      w.cn = { li, nm, vis, cap, vst };
    });

    const bctx = $('cctvBoxes').getContext('2d'), vctx = $('cctvView').getContext('2d');
    const CV_W = 640, CV_H = 480, tmp = new THREE.Vector3();
    function toScreen(x, y, z, cam) {
      tmp.set(x, y, z).applyMatrix4(cam.matrixWorldInverse);
      if (tmp.z > -0.25) return null;
      tmp.applyMatrix4(cam.projectionMatrix);
      return [(tmp.x * 0.5 + 0.5) * CV_W, (-tmp.y * 0.5 + 0.5) * CV_H];
    }
    function boxFrom(cam, x0, x1, y0, y1, z0, z1) {
      let a = 1e9, b = 1e9, c = -1e9, d = -1e9;
      for (let i = 0; i < 8; i++) {
        const p = toScreen(i & 1 ? x1 : x0, i & 2 ? y1 : y0, i & 4 ? z1 : z0, cam);
        if (!p) return null;
        a = Math.min(a, p[0]); b = Math.min(b, p[1]); c = Math.max(c, p[0]); d = Math.max(d, p[1]);
      }
      return { x1: a, y1: b, x2: c, y2: d };
    }
    const occRay = new THREE.Raycaster(), orgV = new THREE.Vector3(), dirV = new THREE.Vector3();
    function clearSight(cam, x, y, z) {
      orgV.copy(cam.position); dirV.set(x, y, z).sub(orgV);
      const dist = dirV.length(); dirV.normalize();
      occRay.set(orgV, dirV); occRay.far = dist - 0.35;
      return !(wallMesh.count && occRay.intersectObject(wallMesh, false).length);
    }

    function drawAruco(g, x, y, sz, id) {
      const n = 5, c = sz / (n + 2);
      g.fillStyle = '#fff'; g.fillRect(x, y, sz, sz); g.fillStyle = '#000';
      let v = (id * 2654435761) >>> 0;
      for (let r = 0; r < n; r++) for (let q = 0; q < n; q++) {
        const edge = r === 0 || q === 0 || r === n - 1 || q === n - 1;
        v = (v * 1664525 + 1013904223) >>> 0;
        if (edge || (v >>> 16) & 1) g.fillRect(x + (q + 1) * c - c * 0.02, y + (r + 1) * c - c * 0.02, c * 1.04, c * 1.04);
      }
    }
    let lastT = 0, hover = null, lastSec = -1, drawCalibOverlay = null;
    function drawBoxes(t) {
      lastT = t;
      const cam = rigs[activeCam].cam, g = bctx;
      g.clearRect(0, 0, CV_W, CV_H);
      const cssW = Math.max(200, $('cctvBoxes').clientWidth);
      const fs = Math.round(Math.min(24, Math.max(12, 11 * CV_W / cssW)));
      g.font = '600 ' + fs + 'px "IBM Plex Mono", ui-monospace, monospace'; g.textBaseline = 'middle'; g.lineJoin = 'round';
      const tag = (txt, x, y, bg, fg) => {
        const w = g.measureText(txt).width + 10, h = fs + 6;
        const px = Math.min(Math.max(2, x), CV_W - w - 2), py = Math.min(Math.max(h + 2, y), CV_H - 2);
        g.fillStyle = bg; g.fillRect(px, py - h, w, h); g.fillStyle = fg; g.fillText(txt, px + 5, py - h / 2 + 1);
      };
      const rect = (b, color, lw) => { g.strokeStyle = color; g.lineWidth = lw; g.strokeRect(b.x1, b.y1, b.x2 - b.x1, b.y2 - b.y1); };
      const pct = (base, i, k) => Math.round(100 * Math.min(0.99, base + 0.015 * Math.sin(t * 1.7 + i * 2.1 + k * 1.3)));
      const lh = fs + 6;
      const rg = rigs[activeCam], lk = rg.lockW, lkEl = $('cctvLock');
      if (rg.frozen) { setText(lkEl, '[PTZ PAUSADO P/ EDIÃ‡ÃƒO]'); lkEl.hidden = false; lkEl.classList.add('paused'); }
      else { lkEl.classList.remove('paused'); if (lk) { setText(lkEl, '[LOCK: ' + lk.name + ']'); lkEl.hidden = false; } else lkEl.hidden = true; }
      workers.forEach((w, i) => {
        let seen = false;
        if (w.active) {
          const bP = boxFrom(cam, w.x - 0.34, w.x + 0.34, 0, 1.98, w.z - 0.34, w.z + 0.34);
          if (bP && bP.x2 > 0 && bP.x1 < CV_W && bP.y2 > 0 && bP.y1 < CV_H && (clearSight(cam, w.x, 1.0, w.z) || clearSight(cam, w.x, 1.75, w.z))) {
            seen = true;
            const bH = w.temCapacete ? boxFrom(cam, w.x - 0.3, w.x + 0.3, 1.38, 1.98, w.z - 0.3, w.z + 0.3) : boxFrom(cam, w.x - 0.22, w.x + 0.22, 1.36, 1.78, w.z - 0.22, w.z + 0.22);
            const bV = boxFrom(cam, w.x - 0.34, w.x + 0.34, 0.42, 1.36, w.z - 0.34, w.z + 0.34);
            const pcol = w.emInfracao ? '#ef4444' : '#38bdf8', pfg = w.emInfracao ? '#fff' : '#04121a';
            const hcol = w.temCapacete ? '#facc15' : '#ef4444', vcol = w.temColete ? '#b6ff3b' : '#ef4444';
            const real = liveMode && w.conf;                                   // modo real: sÃ³ confianÃ§a que o detector enviou, nunca valor inventado
            const ppv = real ? (w.conf.person == null ? null : Math.round(w.conf.person * 100)) : pct(0.94, i, 0);
            const pp = ppv == null ? 'â€“' : ppv;
            rect(bP, pcol, 2.5);
            if (activeCam === 0 && !liveMode) {
              const sz = Math.round(Math.max(40, Math.min(78, (bP.y2 - bP.y1) * 0.32)));
              let ax = bP.x1 - sz - 6; if (ax < 2) ax = Math.min(bP.x2 + 6, CV_W - sz - 2);
              const ay = Math.min(Math.max(2, bP.y1 + lh + 4), CV_H - sz - lh - 4);
              drawAruco(g, ax, ay, sz, w.idNum);
              tag('[ArUco #' + w.idNum + ']', ax, ay + sz + lh, '#0b0f14', '#b6ff3b');
            }
            if (bH) rect(bH, hcol, 2); if (bV) rect(bV, vcol, 2);
            const cv = (k, base, n) => (real ? (w.conf[k] == null ? '' : ' ' + Math.round(w.conf[k] * 100) + '%') : ' ' + pct(base, i, n) + '%');
            const hTxt = w.temCapacete ? 'Capacete OK' + cv('helmet', 0.91, 1) : 'Capacete SEM';
            const vTxt = w.temColete ? 'Colete OK' + cv('vest', 0.89, 2) : 'Colete SEM';
            if (bP.y2 - bP.y1 < 110 || !bH || !bV) {
              tag('P ' + pp + '% C:' + (w.temCapacete ? 'OK' : 'SEM') + ' V:' + (w.temColete ? 'OK' : 'SEM'), bP.x1, bP.y1, pcol, pfg);
            } else {
              tag('Pessoa ' + pp + '%' + (w.identified ? ' Â· #' + w.idNum : ''), bP.x1, bP.y1, pcol, pfg);
              tag(hTxt, bH.x2 + 3, bH.y1 + lh, hcol, w.temCapacete ? '#161200' : '#fff');
              tag(vTxt, bV.x2 + 3, bV.y1 + lh, vcol, w.temColete ? '#0b1400' : '#fff');
            }
          }
        }
        const n = w.cn;
        setText(n.nm, w.identified && !liveMode ? w.name + ' Â· ID #' + w.idNum : w.name);
        setText(n.vis, seen ? 'no campo de visÃ£o' : (w.active ? 'fora de campo' : (liveMode ? 'livre' : 'sem rota')));
        setText(n.cap, 'Capacete ' + (w.capKnown === false ? '?' : w.temCapacete ? 'OK' : 'SEM')); setText(n.vst, 'Colete ' + (w.vestKnown === false ? '?' : w.temColete ? 'OK' : 'SEM'));
        setAttr(n.li, 'data-vis', seen ? '1' : '0');
        n.cap.className = w.temCapacete ? '' : 'bad'; n.vst.className = w.temColete ? '' : 'bad';
      });
      if (drawCalibOverlay) drawCalibOverlay(g, cam);
      if (paint.on && hover) {
        const rr = +sizeEl.value / 16, pts = [];
        for (let k = 0; k <= 24; k++) { const a = k / 24 * Math.PI * 2, p = toScreen(hover.x + Math.cos(a) * rr, 0.04, hover.z + Math.sin(a) * rr, cam); if (!p) { pts.length = 0; break; } pts.push(p); }
        if (pts.length) { g.beginPath(); pts.forEach((p, k) => (k ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]))); g.strokeStyle = paint.erase ? '#ffffff' : '#ff5b5b'; g.lineWidth = 2.5; g.stroke(); }
      }
    }

    function renderCctv(t) {
      const cw = Math.min(320, Math.floor(mainW)), ch = Math.round(cw * 0.75);
      if (cw < 80 || ch > mainH) return;
      const rig = rigs[activeCam], hidden = [];
      const hide = (o) => { if (o.visible) { o.visible = false; hidden.push(o); } };
      rigs.forEach((r) => { hide(r.fov); hide(r.label); }); workers.forEach((w) => hide(w.label)); hide(rig.grp); hide(rig.plate); hide(rig.arm);
      renderer.setViewport(0, 0, cw, ch); renderer.setScissor(0, 0, cw, ch); renderer.setScissorTest(true);
      renderer.render(scene, rig.cam);
      const pr = renderer.getPixelRatio(), sw = Math.floor(cw * pr), sh = Math.floor(ch * pr);
      vctx.drawImage(dom, 0, dom.height - sh, sw, sh, 0, 0, CV_W, CV_H);
      renderer.setScissorTest(false);
      hidden.forEach((o) => { o.visible = true; });
      if (Math.floor(t) !== lastSec) { lastSec = Math.floor(t); $('cctvClock').textContent = new Date().toLocaleString('pt-BR', { hour12: false }); }
      drawBoxes(t);
    }

    const boxesEl = $('cctvBoxes'), screenEl = $('cctvScreen'), ndc = new THREE.Vector2();
    const rc = new THREE.Raycaster(), floorPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), hitV = new THREE.Vector3();
    const paint = { on: false, erase: false, down: false, last: null, cells: 0 };
    function pickFloor(ev) {
      const r = boxesEl.getBoundingClientRect();
      ndc.set(((ev.clientX - r.left) / r.width) * 2 - 1, -(((ev.clientY - r.top) / r.height) * 2 - 1));
      rc.setFromCamera(ndc, rigs[activeCam].cam);
      if (!rc.ray.intersectPlane(floorPlane, hitV)) return null;
      const dFloor = rc.ray.origin.distanceTo(hitV);
      if (wallMesh.count) { const hit = rc.intersectObject(wallMesh, false)[0]; if (hit && hit.distance < dFloor - 0.02) return null; }
      if (Math.abs(hitV.x) > WW / 2 || Math.abs(hitV.z) > WH / 2) return null;
      return { x: hitV.x, z: hitV.z };
    }
    function brushAt(x, z) {
      const rcells = Math.max(0.6, +sizeEl.value / B / 2), u = (x + WW / 2) / CELL - 0.5, v = (z + WH / 2) / CELL - 0.5;
      const rr = Math.ceil(rcells) + 1, c0 = Math.round(u), r0 = Math.round(v);
      let changed = false;
      for (let r = r0 - rr; r <= r0 + rr; r++) {
        for (let c = c0 - rr; c <= c0 + rr; c++) {
          if (r < 0 || c < 0 || r >= ROWS || c >= COLS || Math.hypot(c - u, r - v) > rcells + 0.35) continue;
          const i = r * COLS + c;
          if (wallGrid[i]) continue;
          if (paint.erase) { if (!riskGrid[i]) continue; ctx.fillStyle = '#ffffff'; }
          else { if (riskGrid[i]) continue; ctx.fillStyle = '#ef4444'; }
          ctx.fillRect(c * B, r * B, B, B); changed = true; paint.cells++;
        }
      }
      if (changed) { source = 'planta editada'; scheduleSoft(); }
    }
    function stroke(e) {
      const h = pickFloor(e); hover = h;
      if (!h) { paint.last = null; drawBoxes(lastT); return; }
      if (paint.down) {
        if (paint.last) {
          const dx = h.x - paint.last.x, dz = h.z - paint.last.z, n = Math.max(1, Math.ceil(Math.hypot(dx, dz) / 0.25));
          for (let k = 1; k <= n; k++) brushAt(paint.last.x + dx * k / n, paint.last.z + dz * k / n);
        } else brushAt(h.x, h.z);
        paint.last = h;
      }
      drawBoxes(lastT);
    }
    boxesEl.addEventListener('pointerdown', (e) => {
      if (!paint.on || (e.pointerType === 'mouse' && e.button !== 0)) return;
      e.preventDefault(); boxesEl.setPointerCapture(e.pointerId);
      paint.down = true; paint.last = null; paint.cells = 0; stroke(e);
    });
    boxesEl.addEventListener('pointermove', (e) => { if (paint.on) stroke(e); });
    const endPaint = () => {
      if (!paint.down) return;
      paint.down = false; paint.last = null; softUpdate();
      if (paint.cells) logEvent('Risco ' + (paint.erase ? 'apagado' : 'pintado') + ' pela ' + CAMS[activeCam].name + ': ' + fmt(riskCount) + ' cÃ©lulas de risco no total.', paint.erase ? 'ok' : 'alert');
    };
    boxesEl.addEventListener('pointerup', endPaint); boxesEl.addEventListener('pointercancel', endPaint);
    boxesEl.addEventListener('pointerleave', () => { hover = null; if (!paint.down) drawBoxes(lastT); });
    function paintTip() {
      const tip = $('cctvTip');
      tip.hidden = !paint.on;
      tip.textContent = paint.erase ? 'Arraste sobre o piso para apagar a Ã¡rea de risco' : 'Arraste sobre o piso para pintar a Ã¡rea de risco';
    }
    $('paintBtn').addEventListener('click', () => {
      if (!paint.on && calibState.on) setCalib(false);
      paint.on = !paint.on; $('paintBtn').setAttribute('aria-pressed', String(paint.on));
      screenEl.classList.toggle('paint', paint.on); $('eraseBtn').disabled = !paint.on; paintTip();
      if (!paint.on) { hover = null; drawBoxes(lastT); }
      calibTip();
    });
    $('eraseBtn').addEventListener('click', () => { paint.erase = !paint.erase; $('eraseBtn').setAttribute('aria-pressed', String(paint.erase)); paintTip(); });
    onCamChange();

    // =====================================================================
    // v7: mapa de calor, replay caixa-preta, homografia 4 pontos, fonte de dados
    // =====================================================================
    workers.forEach((w) => { w.hist = []; w.live = false; w.liveX = 0; w.liveZ = 0; w.liveRisk = null; });
    const toPlanPx = (x, z) => [(x + WW / 2) * (W / WW), (z + WH / 2) * (H / WH)];
    const ptEl = (id) => $(id);

    // ===== 6. MAPA DE CALOR E REPLAY CAIXA-PRETA =====
    // ---- 1. mapa de calor histórico ----
    const HEAT_MAX = 22;
    const heatGrid = new Float32Array(COLS * ROWS);
    const heatCv = document.createElement('canvas'); heatCv.width = COLS; heatCv.height = ROWS;
    const heatCtx = heatCv.getContext('2d'), heatImg = heatCtx.createImageData(COLS, ROWS);
    const heatTex = new THREE.CanvasTexture(heatCv);
    heatTex.minFilter = THREE.LinearFilter; heatTex.magFilter = THREE.LinearFilter; heatTex.generateMipmaps = false;
    const heatMesh = new THREE.Mesh(new THREE.PlaneGeometry(WW, WH), new THREE.MeshBasicMaterial({ map: heatTex, transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }));
    heatMesh.rotation.x = -Math.PI / 2; heatMesh.position.y = 0.045; heatMesh.renderOrder = 4; heatMesh.visible = false; heatMesh.layers.set(2);
    scene.add(heatMesh);
    const HSTOPS = [[0, 37, 99, 235, 0], [0.02, 37, 99, 235, 60], [0.25, 37, 99, 235, 150], [0.5, 34, 211, 238, 185], [0.75, 250, 204, 21, 215], [1, 239, 68, 68, 245]];
    function heatColor(v, out, o) {
      let k = 1; while (k < HSTOPS.length - 1 && v > HSTOPS[k][0]) k++;
      const a = HSTOPS[k - 1], b = HSTOPS[k], u = Math.max(0, Math.min(1, (v - a[0]) / (b[0] - a[0])));
      for (let c = 0; c < 4; c++) out[o + c] = a[c + 1] + (b[c + 1] - a[c + 1]) * u;
    }
    function drawHeat() {
      const d = heatImg.data;
      for (let i = 0; i < heatGrid.length; i++) {
        const v = heatGrid[i] <= 0 ? 0 : Math.min(1, Math.pow(heatGrid[i] / HEAT_MAX, 0.6));
        if (v === 0) { d[i * 4 + 3] = 0; continue; }
        heatColor(v, d, i * 4);
      }
      heatCtx.putImageData(heatImg, 0, 0); heatTex.needsUpdate = true;
    }
    let heatOn = false, heatAcc = 0, heatDirty = false, heatDrawAcc = 0;
    function updateHeat(dt) {
      heatAcc += dt;
      if (heatAcc >= 0.1) {
        heatAcc = 0;
        workers.forEach((w) => {
          if (!w.active || !w.emInfracao || !w.tracked) return;
          const c = toCol(w.x), r = toRow(w.z);
          const add = (cc, rr, v) => { if (cc >= 0 && rr >= 0 && cc < COLS && rr < ROWS) heatGrid[rr * COLS + cc] += v; };
          add(c, r, 1); add(c + 1, r, 0.4); add(c - 1, r, 0.4); add(c, r + 1, 0.4); add(c, r - 1, 0.4);
          heatDirty = true;
        });
      }
      heatDrawAcc += dt;
      if (heatDirty && heatOn && heatDrawAcc > 0.25) { heatDrawAcc = 0; heatDirty = false; drawHeat(); }
    }
    function definirHeat(ligado) {
      if (heatOn === ligado) return;
      heatOn = ligado; heatMesh.visible = heatOn;
      const btn = $('toggleHeat');
      btn.setAttribute('aria-pressed', String(heatOn));
      btn.textContent = 'Mapa de calor: ' + (heatOn ? 'ligado' : 'desligado');
      if (heatOn) {
        drawHeat();
        if (liveMode) {
          apiJson('/mapa_calor').then((res) => {
            heatGrid.fill(0);
            const celulas = res && res.celulas ? res.celulas : [];
            celulas.forEach((c) => {
              const idx = Number(c.celula_idx);
              if (idx < 0 || idx >= heatGrid.length) return;
              const taxa = c.taxa_infracao != null ? c.taxa_infracao
                : (c.segundos_infracao != null ? Math.min(1, c.segundos_infracao / Math.max(1, c.segundos_presenca)) : 0);
              heatGrid[idx] = Math.max(heatGrid[idx], taxa * HEAT_MAX);
            });
            heatDirty = true; drawHeat();
          }).catch(() => { /* backend indisponível: mantém o heatGrid local */ });
        }
      }
    }
    $('toggleHeat').addEventListener('click', () => definirHeat(!heatOn));
    $('clearHeat').addEventListener('click', () => { heatGrid.fill(0); heatDirty = false; drawHeat(); logEvent('HistÃ³rico do mapa de calor zerado.'); });

    // ---- 2. replay temporal "caixa-preta" ----
    const HIST_N = 30, HIST_DT = 0.2;
    let histAcc = 0;
    function sampleHist(dt) {
      histAcc += dt;
      if (histAcc < HIST_DT) return;
      histAcc = 0;
      workers.forEach((w) => {
        if (!w.active) return;
        w.hist.push([w.x, w.z, w.emInfracao ? 1 : 0]);
        if (w.hist.length > HIST_N) w.hist.shift();
      });
    }
    trailFor = (text) => {
      const w = workers.find((q) => q.active && new RegExp('(^|[^A-Za-z0-9])' + q.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?![A-Za-z0-9])').test(text)); if (!w) return null;
      const pts = w.hist.slice(); pts.push([w.x, w.z, 1]);
      return { name: w.name, pts };
    };
    const rpl = { group: null, t0: 0, pts: null, marker: null, tag: null, ring: null, end: 0, clock: 0 };
    function clearReplay() {
      if (!rpl.group) return;
      scene.remove(rpl.group);
      rpl.group.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) { if (o.material.map) o.material.map.dispose(); o.material.dispose(); } });
      rpl.group = null; rpl.pts = null;
    }
    playReplay = (trail, stamp) => {
      clearReplay();
      const pts = trail.pts; if (!pts || !pts.length) return;
      const g = new THREE.Group(), n = pts.length, Y = 0.16;
      const pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
      pts.forEach((p, i) => {
        pos.set([p[0], Y, p[1]], i * 3);
        const c = p[2] ? [1, 0.82, 0.1] : [0.13, 0.83, 0.93];
        col.set(c, i * 3);
      });
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(pos, 3)); geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
      const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ vertexColors: true, depthTest: false, transparent: true }));
      const dots = new THREE.Points(geo, new THREE.PointsMaterial({ size: 7, sizeAttenuation: false, vertexColors: true, depthTest: false, transparent: true }));
      line.renderOrder = 15; dots.renderOrder = 16;
      const last = pts[n - 1];
      const ring = new THREE.Mesh(new THREE.RingGeometry(0.55, 0.8, 40), new THREE.MeshBasicMaterial({ color: 0xef4444, transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthTest: false }));
      ring.rotation.x = -Math.PI / 2; ring.position.set(last[0], 0.2, last[1]); ring.renderOrder = 17;
      const marker = new THREE.Mesh(new THREE.SphereGeometry(0.3, 18, 14), new THREE.MeshBasicMaterial({ color: 0xfacc15, depthTest: false }));
      marker.renderOrder = 18; marker.position.set(pts[0][0], 0.55, pts[0][1]);
      const tag = makeLabel('REPLAY ' + trail.name, '#22d3ee'); tag.material.depthTest = false; tag.scale.set(1.5, 0.52, 1); tag.renderOrder = 19;
      g.add(line, dots, ring, marker, tag);
      g.traverse((o) => o.layers.set(2));
      scene.add(g);
      Object.assign(rpl, { group: g, pts, marker, tag, ring, t0: clock.elapsedTime, end: 0 });
      logEvent('Replay 3D: ' + trail.name + ', Ãºltimos ' + f1(Math.max(0, (n - 1) * HIST_DT)) + ' s atÃ© a ocorrÃªncia de ' + stamp + '.');
    };
    // Ponte com a lista de ocorrências: reproduz no 3D o caminho percorrido por
    // uma ocorrência real gravada (Etapa 4). Consome GET /ocorrencia/{id}/trajetoria.
    window.gemeoReproduzirOcorrencia = function (ocorrenciaId) {
      const id = Number(ocorrenciaId);
      if (!isFinite(id)) return Promise.resolve(false);
      return apiJson('/ocorrencia/' + id + '/trajetoria').then((res) => {
        const pontos = (res && res.pontos) ? res.pontos : [];
        const pts = pontos
          .filter((p) => isFinite(Number(p.x_m)) && isFinite(Number(p.z_m)))
          .map((p) => [Number(p.x_m), Number(p.z_m), p.in_risk ? 1 : 0]);
        if (pts.length < 2) {
          logEvent('Ocorrência #' + id + ': trajetória insuficiente para o replay 3D.', 'alert');
          return false;
        }
        playReplay({ name: 'ocorrência #' + id, pts }, 'ocorrência #' + id);
        return true;
      }).catch(() => {
        logEvent('Não foi possível carregar a trajetória da ocorrência #' + id + '.', 'alert');
        return false;
      });
    };
    // Ponte com o assistente contextual (Etapa 8): aproxima a camera na regiao
    // indicada (x_m, z_m do mapa de calor) e liga o mapa de calor historico.
    // A acao e Sugerida pela IA; so roda quando o usuario clica no botao.
    window.gemeoFocarRegiao = function (x_m, z_m) {
      const x = Number(x_m), z = Number(z_m);
      if (!isFinite(x) || !isFinite(z)) return;
      focoX = clamp(x, -WW / 2, WW / 2);
      focoZ = clamp(z, -WH / 2, WH / 2);
      tR = 18;   // zoom suave ate a regiao
      definirHeat(true);
      logEvent('Assistente: região ' + focoX.toFixed(1) + ' m, ' + focoZ.toFixed(1) + ' m no gêmeo com o mapa de calor ligado.');
    };

    function updateReplay(t) {
      if (!rpl.group) return;
      const n = rpl.pts.length, p = Math.min(1, (t - rpl.t0) / 5), f = p * (n - 1), i = Math.min(n - 1, Math.floor(f)), u = f - i;
      const a = rpl.pts[i], b = rpl.pts[Math.min(n - 1, i + 1)];
      const x = a[0] + (b[0] - a[0]) * u, z = a[1] + (b[1] - a[1]) * u;
      const pulse = 1 + 0.15 * Math.sin(t * 9);
      rpl.marker.position.set(x, 0.55 + 0.08 * Math.sin(t * 9), z); rpl.marker.scale.setScalar(pulse);
      rpl.tag.position.set(x, 1.45, z);
      const rs = 1 + 0.25 * Math.sin(t * 6); rpl.ring.scale.set(rs, rs, 1);
      if (p >= 1) { if (!rpl.end) rpl.end = t; if (t - rpl.end > 4) clearReplay(); }
    }

    // ===== 7. CALIBRADOR DE HOMOGRAFIA E SNAPSHOT =====
    // ---- 3. calibrador de homografia (4 pontos) ----
    function solveH(src, dst) {                      // imagem -> planta; resolve o sistema 8x8 por eliminaÃ§Ã£o de Gauss
      const A = [];
      for (let i = 0; i < 4; i++) {
        const [x, y] = src[i], [u, v] = dst[i];
        A.push([x, y, 1, 0, 0, 0, -u * x, -u * y, u]);
        A.push([0, 0, 0, x, y, 1, -v * x, -v * y, v]);
      }
      for (let c = 0; c < 8; c++) {
        let m = c; for (let r = c + 1; r < 8; r++) if (Math.abs(A[r][c]) > Math.abs(A[m][c])) m = r;
        if (Math.abs(A[m][c]) < 1e-9) return null;
        [A[c], A[m]] = [A[m], A[c]];
        for (let r = 0; r < 8; r++) {
          if (r === c) continue;
          const k = A[r][c] / A[c][c];
          for (let j = c; j < 9; j++) A[r][j] -= k * A[c][j];
        }
      }
      const h = A.map((row, i) => row[8] / row[i]);
      return [[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1]];
    }
    const applyH = (H, x, y) => { const w = H[2][0] * x + H[2][1] * y + H[2][2]; return [(H[0][0] * x + H[0][1] * y + H[0][2]) / w, (H[1][0] * x + H[1][1] * y + H[1][2]) / w]; };
    const fnum = (v) => (Math.abs(v) < 0.001 && v !== 0 ? v.toExponential(2) : v.toFixed(3)).replace('.', ',');
    const calib3D = new THREE.Group(); calib3D.layers.set(2); scene.add(calib3D);
    function rebuildCalib3D() {
      while (calib3D.children.length) {
        const o = calib3D.children.pop();
        o.traverse((q) => { if (q.geometry) q.geometry.dispose(); if (q.material) { if (q.material.map) q.material.map.dispose(); q.material.dispose(); } });
      }
      const quads = calibs.filter(Boolean).map((c) => c.world);
      if (calibState.on && calibState.cur && calibState.cur.world.length) quads.push(calibState.cur.world);
      quads.forEach((q) => {
        const pts = q.map((p) => new THREE.Vector3(p[0], 0.09, p[1]));
        const lg = new THREE.BufferGeometry().setFromPoints(pts);
        const loop = pts.length === 4 ? new THREE.LineLoop(lg, new THREE.LineBasicMaterial({ color: 0xb6ff3b, depthTest: false })) : new THREE.Line(lg, new THREE.LineBasicMaterial({ color: 0xb6ff3b, depthTest: false }));
        loop.renderOrder = 12; calib3D.add(loop);
        if (pts.length === 4) {
          const fg = new THREE.BufferGeometry().setFromPoints([pts[0], pts[1], pts[2], pts[0], pts[2], pts[3]]);
          const fill = new THREE.Mesh(fg, new THREE.MeshBasicMaterial({ color: 0xb6ff3b, transparent: true, opacity: 0.2, side: THREE.DoubleSide, depthWrite: false, depthTest: false }));
          fill.renderOrder = 11; calib3D.add(fill);
        }
        pts.forEach((p, k) => {
          const pin = new THREE.Mesh(new THREE.SphereGeometry(0.16, 12, 10), new THREE.MeshBasicMaterial({ color: 0xb6ff3b, depthTest: false }));
          pin.position.set(p.x, 0.25, p.z); pin.renderOrder = 13; calib3D.add(pin);
          const lb = makeLabel('P' + (k + 1), '#b6ff3b'); lb.material.depthTest = false; lb.scale.set(0.95, 0.33, 1); lb.position.set(p.x, 0.85, p.z); lb.renderOrder = 14; calib3D.add(lb);
        });
      });
      calib3D.traverse((o) => o.layers.set(2));
    }
    function calibTip() {
      const tip = $('cctvTip');
      if (!calibState.on) { if (!paint.on) tip.hidden = true; return; }
      const n = calibState.cur ? calibState.cur.world.length : 0;
      tip.hidden = false; tip.textContent = 'CalibraÃ§Ã£o: clique no ponto P' + Math.min(4, n + 1) + ' de 4 sobre o piso';
    }
    function setCalib(on) {
      if (on === calibState.on) return;
      if (on && paint.on) $('paintBtn').click();
      calibState.on = on;
      $('calibBtn').setAttribute('aria-pressed', String(on));
      screenEl.classList.toggle('calib', on);
      if (on) { calibs[activeCam] = null; calibState.cur = { world: [], img: [] }; }
      else calibState.cur = null;
      calibTip(); rebuildCalib3D(); drawCamLayer(); drawBoxes(lastT);
    }
    $('calibBtn').addEventListener('click', () => setCalib(!calibState.on));
    function finishCalib() {
      const cur = calibState.cur, cam = rigs[activeCam].cam, name = CAMS[activeCam].name;
      const dst = cur.world.map((p) => toPlanPx(p[0], p[1]));
      const Hm = solveH(cur.img, dst);
      if (!Hm || Hm.some((r) => r.some((v) => !isFinite(v)))) {
        logEvent('CalibraÃ§Ã£o de ' + name + ' invÃ¡lida: os 4 pontos nÃ£o podem ficar alinhados. Tente de novo.', 'alert');
        calibState.cur = { world: [], img: [] }; calibTip(); rebuildCalib3D(); drawCamLayer(); return;
      }
      let err = 0;
      for (let i = 0; i < 4; i++) { const q = applyH(Hm, cur.img[i][0], cur.img[i][1]); err += Math.hypot(q[0] - dst[i][0], q[1] - dst[i][1]); }
      err /= 4;
      // conferÃªncia independente: centro da imagem projetado por H x raio da cÃ¢mera atÃ© o piso
      let chk = '';
      rc.setFromCamera(ndc.set(0, 0), cam);
      if (rc.ray.intersectPlane(floorPlane, hitV)) {
        const ref = toPlanPx(hitV.x, hitV.z), q = applyH(Hm, CV_W / 2, CV_H / 2);
        chk = ' Â· erro no centro da imagem: ' + fnum(Math.hypot(q[0] - ref[0], q[1] - ref[1])) + ' px';
      }
      calibs[activeCam] = { world: cur.world.slice(), img: cur.img.slice(), plan: dst, H: Hm };
      try { localStorage.setItem('epi.gemeo.calibs', JSON.stringify(calibs.map((c) => c ? { world: c.world, img: c.img, plan: c.plan, H: c.H } : null))); } catch (e) { /* localStorage indisponÃ­vel */ }
      // Persiste no backend via POST /calibracao
      try {
        const payload = { camId: CAMS[activeCam].id, frame: { w: CV_W, h: CV_H }, img: cur.img.slice(), world: cur.world.slice(), plan: dst, H: Hm, updatedAt: Date.now() };
        fetch('/calibracao', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }).then(r => { if (!r.ok) logEvent('Falha ao salvar calibracao no backend (HTTP ' + r.status + ').', 'alert'); }).catch(e => logEvent('Backend indisponivel para /calibracao: ' + e.message, 'alert')); } catch (e) { /* fetch nao disponivel */ }
      const rows = Hm.map((r) => '[' + r.map(fnum).join('  ') + ']').join(' ');
      logEvent('Homografia 3Ã—3 de ' + name + ' (imagem 640Ã—480 â†’ planta 320Ã—240): H = ' + rows + ' Â· erro de reprojeÃ§Ã£o: ' + fnum(err) + ' px' + chk + '.', 'ok');
      setCalib(false);
    }
    boxesEl.addEventListener('pointerdown', (e) => {
      if (!calibState.on || (e.pointerType === 'mouse' && e.button !== 0)) return;
      e.preventDefault();
      const h = pickFloor(e), r = boxesEl.getBoundingClientRect();
      if (!h) { const tip = $('cctvTip'); tip.textContent = 'Ponto fora do piso visÃ­vel. Escolha outro ponto.'; return; }
      const cur = calibState.cur;
      cur.world.push([h.x, h.z]); cur.img.push([(e.clientX - r.left) / r.width * CV_W, (e.clientY - r.top) / r.height * CV_H]);
      calibTip(); rebuildCalib3D(); drawCamLayer(); drawBoxes(lastT);
      if (cur.world.length === 4) finishCalib();
    });
    // pinos e quadrilÃ¡tero sobre a imagem da cÃ¢mera (ancorados no piso: acompanham a PTZ)
    drawCalibOverlay = (g, cam) => {
      const q = calibs[activeCam] ? calibs[activeCam].world : (calibState.on && calibState.cur ? calibState.cur.world : null);
      if (!q || !q.length) return;
      const sp = q.map((p) => toScreen(p[0], 0.02, p[1], cam));
      if (sp.every(Boolean)) {
        g.beginPath(); sp.forEach((p, k) => (k ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])));
        if (sp.length === 4) { g.closePath(); g.fillStyle = 'rgba(182,255,59,0.14)'; g.fill(); }
        g.strokeStyle = '#b6ff3b'; g.lineWidth = 2.5; g.stroke();
      }
      g.textAlign = 'center';
      sp.forEach((p, k) => {
        if (!p) return;
        g.beginPath(); g.arc(p[0], p[1], 7, 0, Math.PI * 2); g.fillStyle = '#b6ff3b'; g.fill(); g.lineWidth = 2; g.strokeStyle = '#0b1400'; g.stroke();
        g.fillStyle = '#b6ff3b'; g.strokeStyle = '#000'; g.lineWidth = 3; g.strokeText('P' + (k + 1), p[0], p[1] - 12); g.fillText('P' + (k + 1), p[0], p[1] - 12);
      });
      g.textAlign = 'start';
    };

    // ---- 4. fonte de dados: simulaÃ§Ã£o x dados reais (Arduino) ----
    // A simulaÃ§Ã£o e os dados reais NUNCA se misturam: ao trocar de fonte, avatares, calor, histÃ³rico e conformidade sÃ£o zerados,
    // e sem dados reais a cena fica vazia (nenhum avatar fictÃ­cio Ã© mostrado como se fosse real). O formato das mensagens e o
    // estado da conexÃ£o ficam em fonte_dados.js (GemeoFonte); aqui sÃ³ se aplica o quadro normalizado Ã  cena.
    const wsBtn = $('wsToggle'), wsPanel = $('wsPanel'), wsStatus = $('wsStatus'), wsUrl = $('wsUrl');
    const slotPorId = new Map();                 // id da trilha real -> avatar do pool
    const AUSENTE_S = 1.5;                       // tolerÃ¢ncia a falhas de 1-2 quadros do detector antes de liberar o avatar
    let semPosicao = 0, semVaga = 0, avisouVaga = false, avisouPosicao = false;
    const ponte = window.GemeoPonte = { conectado: !!(window.GemeoCanal && window.GemeoCanal.conectado), receber: () => {}, canalConectou: () => {}, parar: () => {} };
    const fonte = GemeoFonte.criarFonte({ staleMs: 3000, aoMudarEstado: (st) => onEstadoFonte(st) });
    const setStatus = (txt, k) => { wsStatus.textContent = txt; wsStatus.dataset.k = k || ''; };

    function renderFonte() {
      const st = fonte.estado();
      const modo = !liveMode ? 'sim' : st.estado === 'ativa' ? 'real' : 'off';
      wsBtn.dataset.mode = modo;
      const rot = modo === 'sim' ? 'SIMULAÃ‡ÃƒO' : modo === 'real' ? 'DADOS REAIS' : 'SEM DADOS REAIS';
      $('wsLabel').innerHTML = '<span class="mt-long">Fonte: </span>' + rot;
      $('fonteMarca').textContent = modo === 'sim' ? 'SIMULAÃ‡ÃƒO Â· dados fictÃ­cios, nÃ£o sÃ£o da cÃ¢mera' : modo === 'off' ? 'SEM DADOS REAIS Â· ' + (st.rotulo || 'escolha uma fonte') : '';
      $('fonteMarca').dataset.modo = modo;
      $('confCard').querySelector('.k-lbl').textContent = 'Conformidade Pessoa-Frame' + (modo === 'sim' ? ' Â· simulada' : modo === 'real' ? ' Â· real' : '');
      $('cctvOrigem').textContent = modo === 'sim' ? 'VISTA VIRTUAL Â· detecÃ§Ãµes simuladas' : 'VISTA VIRTUAL Â· posiÃ§Ãµes reais do detector';
      $('cctvRec').textContent = 'VIRTUAL';
      $('wsSim').hidden = !liveMode;
      const det = modo === 'real' ? ' Â· ' + (st.taxa ? st.taxa.toFixed(1) + ' quadros/s' : '') + (st.latenciaMs != null ? ' Â· atraso â‰ˆ ' + Math.round(st.latenciaMs) + ' ms' : '') : '';
      if (liveMode) setStatus((modo === 'real' ? 'Recebendo dados reais' : 'Sem dados reais') + (st.rotulo && modo !== 'real' ? ': ' + st.rotulo : '') + det + '.', modo === 'real' ? 'ok' : 'bad');
      else setStatus('SimulaÃ§Ã£o ativa: os operÃ¡rios e as infraÃ§Ãµes sÃ£o fictÃ­cios. Para usar dados reais, escolha uma fonte abaixo.', '');
    }
    function openPanel(open) {
      wsPanel.hidden = !open; wsBtn.setAttribute('aria-expanded', String(open));
      if (open) { renderFonte(); (liveMode ? $('wsSim') : $('wsPainel')).focus(); }
    }

    function liberar(w) {
      if (w.liveId != null) slotPorId.delete(w.liveId);
      w.liveId = null; w.active = false; w.live = false; w.g.visible = false; w.liveRisk = null; w.hist.length = 0; w.semPos = false;
      w.inRisk = false; w.emInfracao = false; w.conf = null; w.capKnown = w.vestKnown = undefined; w.temCapacete = w.temColete = true;
      w.name = 'OP-0' + (w.slot + 1); w.label.userData.redraw(w.name); w.label.visible = false;
      if (w.totem) { w.totem.pts.length = 0; w.totem.key = ''; }
    }
    const liberarTodos = () => { workers.forEach(liberar); slotPorId.clear(); semPosicao = 0; };
    function zerarAcumulados() {                // dados de uma fonte nÃ£o podem contaminar os da outra
      totalPessoaFrames = 0; conformesPessoaFrames = 0; sampleAcc = 0; heatGrid.fill(0); heatDirty = false; drawHeat(); clearReplay();
      workers.forEach((w) => { w.invasions = 0; });
    }
    function onEstadoFonte(st) {
      if (!liveMode) return;
      if (st.estado !== 'ativa' && workers.some((w) => w.liveId != null)) liberarTodos();   // sem sinal: nada de posiÃ§Ã£o "congelada" como se fosse atual
      const tipo = st.estado === 'ativa' ? 'ok' : (st.estado === 'aguardando' || st.estado === 'conectando') ? '' : 'alert';
      if (st.rotulo) logEvent('Fonte real: ' + st.rotulo + '.', tipo);
      renderFonte(); refreshUI();
    }
    function entrarReal(abrir) {
      closeSockUi();
      if (!liveMode) {
        liveMode = true; liberarTodos(); zerarAcumulados(); avisouVaga = avisouPosicao = false; semVaga = 0;
        workers.forEach((w) => { w.nodes.risk.disabled = true; });
        logEvent('Modo DADOS REAIS ativado: a simulaÃ§Ã£o foi desligada e os acumulados foram zerados.', 'ok');
      }
      abrir(); renderFonte(); refreshUI();
    }
    function closeSockUi() { /* o WebSocket Ã© gerenciado por GemeoFonte; mantido por clareza */ }
    function voltarSimulacao(msg) {
      if (!liveMode) { openPanel(false); return; }
      fonte.parar(); liveMode = false; liberarTodos(); zerarAcumulados();
      workers.forEach((w) => { w.nodes.risk.disabled = false; });
      workers.forEach(spawn);
      logEvent(msg || 'Modo SIMULAÃ‡ÃƒO ativado: os dados exibidos voltam a ser fictÃ­cios.', 'ok');
      renderFonte(); refreshUI(); openPanel(false);
    }

    // Projeta um ponto da imagem (u,v em pixels 640Ã—480) para coordenadas do mundo (x,z em metros)
    // usando a homografia H da cÃ¢mera ativa. Retorna {x,z} ou null se nÃ£o houver calibraÃ§Ã£o vÃ¡lida
    // ou o ponto cair fora dos limites da planta.
    function projImgParaPlano(u, v, camIdx) {
      const cal = calibs[camIdx];
      // Usa a resolucao em que a H foi calculada (cal.frame, padrao 640x480 para
      // camera virtual; 720x480 quando calibrado via /snapshot ou normalizado do detector).
      if (!cal || !Array.isArray(cal.H) || cal.H.length !== 3) return null;
      const cf = cal && cal.frame ? cal.frame : { w: 640, h: 480 };
      // A imagem da câmera virtual tem 640x480; a H foi calculada no frame da
      // calibração (cf), então os pontos são escalados para esse referencial.
      const uCal = u * (cf.w / CV_W);
      const vCal = v * (cf.h / CV_H);
      const [px, py] = applyH(cal.H, uCal, vCal);
      if (!isFinite(px) || !isFinite(py)) return null;
      const sx = W / WW, sy = H / WH;          // 8 px/m em ambos os eixos (planta 320Ã—240 â†’ 40Ã—30 m)
      const x = px / sx - WW / 2;
      const z = py / sy - WH / 2;
      if (Math.abs(x) > WW / 2 || Math.abs(z) > WH / 2) return null;
      return { x, z };
    }

    function aplicarQuadro(q) {
      const t = clock.elapsedTime; let sp = 0;
      for (const m of q.workers) {
        let w = slotPorId.get(m.id);
        if (!w) {
          w = workers.find((k) => k.liveId == null);
          if (!w) { semVaga++; if (!avisouVaga) { avisouVaga = true; logEvent('Mais de ' + POOL_N + ' trabalhadores ao mesmo tempo: os excedentes nÃ£o sÃ£o exibidos no 3D (limite do pool de avatares).', 'alert'); } continue; }
          slotPorId.set(m.id, w); w.liveId = m.id; w.name = 'ID ' + m.id; w.label.userData.redraw(w.name);
          w.hist.length = 0; w.invasions = 0; w.inRisk = false; w.live = true; w.path = null;
          if (w.totem) { w.totem.pts.length = 0; w.totem.key = ''; }
        }
        w.lastMsgT = t;
        w.conf = m.confidence;
        w.capKnown = m.ppe.helmet !== null; w.vestKnown = m.ppe.vest !== null;
        w.temCapacete = w.capKnown ? m.ppe.helmet : true; w.temColete = w.vestKnown ? m.ppe.vest : true;
        w.liveRisk = m.inRisk;
        if (m.position) {
          w.semPos = false;
          w.liveX = Math.max(-WW / 2 + 0.25, Math.min(WW / 2 - 0.25, m.position.x)); w.liveZ = Math.max(-WH / 2 + 0.25, Math.min(WH / 2 - 0.25, m.position.z));
          if (!w.active) { w.active = true; w.g.visible = true; w.x = w.liveX; w.z = w.liveZ; w.tx = w.x; w.tz = w.z; w.tracked = true; w.lastSeenT = t; w.g.position.set(w.x, 0, w.z); }
        } else if (m.image && m.image.foot) {                      // sÃ³ caixa na imagem: projetar via homografia cÃ¢meraâ†’planta
          const pp = projImgParaPlano(m.image.foot[0], m.image.foot[1], activeCam);
          if (pp) {
            w.semPos = false;
            w.liveX = Math.max(-WW / 2 + 0.25, Math.min(WW / 2 - 0.25, pp.x)); w.liveZ = Math.max(-WH / 2 + 0.25, Math.min(WH / 2 - 0.25, pp.z));
            if (!w.active) { w.active = true; w.g.visible = true; w.x = w.liveX; w.z = w.liveZ; w.tx = w.x; w.tz = w.z; w.tracked = true; w.lastSeenT = t; w.g.position.set(w.x, 0, w.z); }
          } else {
            sp++; w.semPos = true;
            if (w.active) { w.active = false; w.g.visible = false; }
          }
        } else {                                                    // nem posiÃ§Ã£o nem imagem
          sp++; w.semPos = true;
          if (w.active) { w.active = false; w.g.visible = false; }
        }
      }
      semPosicao = sp;
      if (sp && !avisouPosicao) { avisouPosicao = true; logEvent('Chegaram trilhas sem posiÃ§Ã£o na planta (sÃ³ caixa na imagem). Elas contam como pessoas, mas sÃ³ aparecem no 3D depois da calibraÃ§Ã£o cÃ¢meraâ†’planta.', 'alert'); }
    }
    function liveStep(w, dt, t) {
      if (w.liveId != null && t - w.lastMsgT > AUSENTE_S) { liberar(w); return; }       // trilha sumiu do detector
      if (!w.live || !w.active) return;
      const k = 1 - Math.exp(-10 * dt), dx = w.liveX - w.x, dz = w.liveZ - w.z;
      w.moving = Math.hypot(dx, dz) > 0.03;
      w.x += dx * k; w.z += dz * k; w.tx = w.x; w.tz = w.z;
      w.g.position.set(w.x, 0, w.z);
      w.inner.position.y = w.moving ? Math.abs(Math.sin(t * 9 + w.speed)) * 0.07 : 0;
    }

    // Canal 1: socket do prÃ³prio painel (WebUI do Arduino App Lab). O mÃ³dulo tela_gemeo.js repassa as mensagens "telemetria_gemeo".
    ponte.receber = (p) => { if (liveMode && fonte.estado().canal === 'painel') fonte.receber(p); };
    ponte.canalConectou = (sim) => { ponte.conectado = sim; if (liveMode) fonte.canalConectou(sim); };
    ponte.parar = () => { if (liveMode) voltarSimulacao('GÃªmeo 3D: sessÃ£o encerrada; voltando ao modo simulaÃ§Ã£o.'); };
    $('wsPainel').addEventListener('click', () => { entrarReal(() => fonte.usarCanal('painel', ponte.conectado)); openPanel(false); });
    // Canal 2 (avanÃ§ado): WebSocket externo, por exemplo o servidor de testes tools/ws_teste_gemeo.py.
    function wsConnect() {
      const url = wsUrl.value.trim();
      if (!/^wss?:\/\//i.test(url)) { setStatus('Use um endereÃ§o que comece com ws:// ou wss://.', 'bad'); return; }
      entrarReal(() => fonte.conectarWS(url)); openPanel(false);
    }
    wsBtn.addEventListener('click', () => openPanel(wsPanel.hidden));
    $('wsConnect').addEventListener('click', wsConnect);
    $('wsSim').addEventListener('click', () => voltarSimulacao());
    $('wsCancel').addEventListener('click', () => openPanel(false));
    wsUrl.addEventListener('keydown', (e) => { if (e.key === 'Enter') wsConnect(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !wsPanel.hidden) { openPanel(false); wsBtn.focus(); } });
    document.addEventListener('pointerdown', (e) => { if (!wsPanel.hidden && !wsPanel.contains(e.target) && !wsBtn.contains(e.target)) openPanel(false); });
    renderFonte();

    // ---------- CÃ¢mera Orbital ----------
    const HOME = { theta: -0.35, phi: 0.92, r: 36 };
    let tTheta = HOME.theta, tPhi = HOME.phi, tR = HOME.r, theta = tTheta, phi = tPhi, rad = tR;
    let focoX = 0, focoZ = 0;   // ponto de interesse: "ver regiao" do assistente (Etapa 8)
    const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
    function placeCamera() {
      camera.position.set(
        focoX + rad * Math.sin(phi) * Math.sin(theta),
        rad * Math.cos(phi),
        focoZ + rad * Math.sin(phi) * Math.cos(theta)
      );
      camera.lookAt(focoX, 0.6, focoZ);
    }
    const ptrs = new Map(); let lastPinch = 0;
    const pdist = () => { const a = [...ptrs.values()]; return Math.hypot(a[0].x - a[1].x, a[0].y - a[1].y); };
    dom.addEventListener('pointerdown', (e) => {
      dom.setPointerCapture(e.pointerId);
      ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (ptrs.size === 2) lastPinch = pdist();
    });
    dom.addEventListener('pointermove', (e) => {
      const prev = ptrs.get(e.pointerId);
      if (!prev) return;
      if (ptrs.size === 1) {
        tTheta -= (e.clientX - prev.x) * 0.007;
        tPhi = clamp(tPhi - (e.clientY - prev.y) * 0.007, 0.12, 1.5);
        ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
      } else if (ptrs.size === 2) {
        ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
        const d = pdist();
        if (lastPinch > 0 && d > 0) tR = clamp(tR * lastPinch / d, 8, 70);
        lastPinch = d;
      }
    });
    const release = (e) => { ptrs.delete(e.pointerId); lastPinch = 0; };
    dom.addEventListener('pointerup', release);
    dom.addEventListener('pointercancel', release);
    dom.addEventListener('wheel', (e) => { e.preventDefault(); tR = clamp(tR * Math.exp(e.deltaY * 0.0012), 8, 70); }, { passive: false });
    $('resetCam').addEventListener('click', () => { tTheta = HOME.theta; tPhi = HOME.phi; tR = HOME.r; });

    function resize() {
      const r = viewer.getBoundingClientRect();
      if (!r.width || !r.height) return;
      renderer.setSize(r.width, r.height, false); mainW = r.width; mainH = r.height;
      camera.aspect = r.width / r.height; camera.updateProjectionMatrix();
    }
    if (window.ResizeObserver) new ResizeObserver(resize).observe(viewer);
    window.addEventListener('resize', resize);
    resize();
  // =========================================================================
  // ===== 8. PONTE DE DADOS E LOOP DE RENDERIZAÇÃO =====
  // =========================================================================

    // ---------- LaÃ§o Principal ----------
    const clock = new THREE.Clock();
    let uiAcc = 1, cctvAcc = 1, trackAcc = 1;
    // Desempenho: 30 quadros/s com a cena em movimento; 6 quadros/s quando estÃ¡ parada (sem operÃ¡rio ativo, cÃ¢mera assentada, sem ediÃ§Ã£o).
    const FPS_ATIVO = 30, FPS_OCIOSO = 6;
    let ultimoDesenho = 0, dtAcum = 0;
    const perf = { quadros: 0, desde: performance.now(), fps: 0, ms: 0, ocioso: false };
    window.GemeoPerf = {
      snapshot() { const i = renderer.info; return { fps: perf.fps, msPorQuadro: perf.ms, ocioso: perf.ocioso, chamadas: i.render.calls, triangulos: i.render.triangles, geometrias: i.memory.geometries, texturas: i.memory.textures, pixelRatio: renderer.getPixelRatio() }; },
    };
    function frame(agora) {
      requestAnimationFrame(frame);
      if (document.hidden || !viewer.offsetParent) { clock.getDelta(); dtAcum = 0; return; }   // aba GÃªmeo 3D fechada: nÃ£o simula nem desenha
      const parado = !workers.some((w) => w.active) && Math.abs(tTheta - theta) + Math.abs(tPhi - phi) + Math.abs(tR - rad) < 1e-3 && extrudeProgress >= 1 && !paint.on && !calibState.on && !rpl.group;
      const alvo = 1000 / (parado ? FPS_OCIOSO : FPS_ATIVO);
      if (agora - ultimoDesenho < alvo - 2) return;                                        // pula o quadro: o relÃ³gio acumula e o prÃ³ximo dt compensa
      ultimoDesenho = agora; perf.ocioso = parado;
      const ini = performance.now();
      if (liveMode) { const q = fonte.consumir(); if (q) aplicarQuadro(q); }
      const dt = Math.min(clock.getDelta(), 0.1), t = clock.elapsedTime;
      theta += (tTheta - theta) * 0.18; phi += (tPhi - phi) * 0.18; rad += (tR - rad) * 0.18;
      placeCamera();

      // AnimaÃ§Ã£o suave de extrusÃ£o 2D -> 3D
      if (extrudeProgress < 1) {
        extrudeProgress = Math.min(1, extrudeProgress + dt * 2.4);
        const ease = 1 - Math.pow(1 - extrudeProgress, 3);
        buildGroup.scale.y = Math.max(0.01, ease);
      } else {
        buildGroup.scale.y = 1;
      }

      riskMat.emissiveIntensity = 0.55 + 0.35 * Math.sin(t * 3.2);
      const blinkOn = Math.floor(t * (reduceMotion ? 2 : 5)) % 2 === 0;
      let changed = false;
      workers.forEach((w) => {
        if (liveMode) liveStep(w, dt, t); else stepWorker(w, dt, t);
        if (!w.active) return;
        const now = (liveMode && w.liveRisk !== null) ? w.liveRisk : riskGrid[toRow(w.z) * COLS + toCol(w.x)] === 1;
        if (now !== w.inRisk) {
          w.inRisk = now; changed = true;
          if (now) { w.invasions++; logEvent(w.name + ' entrou em Ã¡rea de risco (X ' + f1(w.x) + ' Â· Z ' + f1(w.z) + ').', 'alert'); }
          else logEvent(w.name + ' saiu da Ã¡rea de risco.', 'ok');
        }
        w.hat.visible = w.temCapacete;
        w.vest.visible = w.temColete;

        const emInfracao = w.inRisk || !w.temCapacete || !w.temColete;
        if (emInfracao !== w.emInfracao) changed = true;
        w.emInfracao = emInfracao;
        if (emInfracao) {
          const hot = blinkOn;
          w.shirtMat.color.setHex(hot ? ALERT_RED : SHIRT_HEX);
          w.shirtMat.emissive.setHex(hot ? ALERT_GLOW : 0x000000);
          w.vestMat.emissive.setHex(hot ? ALERT_GLOW : VEST_EMISSIVE);
        } else {
          w.shirtMat.color.setHex(SHIRT_HEX); w.shirtMat.emissive.setHex(0x000000); w.vestMat.emissive.setHex(VEST_EMISSIVE);
        }
      });
      trackAcc += dt;
      if (trackAcc >= 0.1) { trackAcc = 0; updateTracking(t); }
      updatePTZ(t, dt);
      updateTotems(t, blinkOn);
      updateHeat(dt); sampleHist(dt); updateReplay(t);
      sampleConformity(dt);
      uiAcc += dt;
      if (changed || uiAcc > 0.15) { uiAcc = 0; refreshUI(); }
      // SÃ³ as paredes/pilares/vergas projetam sombra e eles sÃ£o estÃ¡ticos: o mapa de sombras sÃ³ Ã© refeito quando a estrutura muda ou durante a extrusÃ£o.
      if (shadowDirty || extrudeProgress < 1) { renderer.shadowMap.needsUpdate = true; shadowDirty = extrudeProgress < 1; }
      cctvAcc += dt;
      if (cctvAcc >= 1 / 12 && $('pip').dataset.size !== 'min') { cctvAcc = 0; renderCctv(t); }   // monitor minimizado nÃ£o precisa do segundo desenho
      renderer.setScissorTest(false); renderer.setViewport(0, 0, mainW, mainH);
      renderer.render(scene, camera);
      perf.quadros++; perf.ms = perf.ms * 0.9 + (performance.now() - ini) * 0.1;
      if (agora - perf.desde >= 1000) { perf.fps = perf.quadros * 1000 / (agora - perf.desde); perf.quadros = 0; perf.desde = agora; }
    }
    requestAnimationFrame(frame);

    return {
      rebuild(anim) { buildMeshes(anim); workers.forEach(spawn); refreshUI(); },
      rebuildMeshes(anim) { buildMeshes(anim); },
      onCamChange,
      autoPlaceCams
    };
  }

  // ---------- Seletor de CÃ¢meras ----------
  const camCtx = $('camLayer').getContext('2d');
  function drawCamLayer() {
    const g = camCtx, CW = 640, CH = 480, kx = CW / WW, kz = CH / WH;
    g.clearRect(0, 0, CW, CH);
    CAMS.forEach((d, i) => {
      const on = i === activeCam, px = (d.pos[0] + WW / 2) * kx, py = (d.pos[2] + WH / 2) * kz;
      const dx = d.target[0] - d.pos[0], dz = d.target[2] - d.pos[2], yaw = camYaw[i];
      if (on) {
        const hf = 2 * Math.atan(Math.tan(d.fov * Math.PI / 360) * 4 / 3), len = Math.hypot(dx, dz) * 1.15 * kx;
        g.beginPath(); g.moveTo(px, py); g.arc(px, py, len, yaw - hf / 2, yaw + hf / 2); g.closePath();
        g.fillStyle = 'rgba(110, 190, 0, 0.28)'; g.fill(); g.strokeStyle = '#2f7d00'; g.lineWidth = 2; g.stroke();
      }
      g.save(); g.translate(px, py); g.rotate(yaw);
      g.beginPath(); g.rect(-11, -8, 16, 16); g.moveTo(5, -5); g.lineTo(15, -9); g.lineTo(15, 9); g.lineTo(5, 5); g.closePath();
      g.fillStyle = on ? '#b6ff3b' : '#7c8a68'; g.strokeStyle = '#0b1400'; g.lineWidth = 3; g.stroke(); g.fill();
      g.restore();
      g.font = '700 22px monospace'; g.textAlign = 'center'; g.lineWidth = 5; g.strokeStyle = '#fff'; g.fillStyle = '#0b1400';
      g.strokeText(d.id, px, py - 18); g.fillText(d.id, px, py - 18);
    });
    const quads = calibs.filter(Boolean).map((c) => c.world);
    if (calibState.on && calibState.cur && calibState.cur.world.length) quads.push(calibState.cur.world);
    quads.forEach((q) => {
      const pts = q.map((p) => [(p[0] + WW / 2) * kx, (p[1] + WH / 2) * kz]);
      g.beginPath(); pts.forEach((p, k) => (k ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])));
      if (pts.length === 4) { g.closePath(); g.fillStyle = 'rgba(182, 255, 59, 0.22)'; g.fill(); }
      g.lineWidth = 3; g.strokeStyle = '#6aa800'; g.stroke();
      pts.forEach((p, k) => {
        g.beginPath(); g.arc(p[0], p[1], 7, 0, Math.PI * 2); g.fillStyle = '#b6ff3b'; g.fill(); g.lineWidth = 2; g.strokeStyle = '#0b1400'; g.stroke();
        g.font = '700 14px monospace'; g.textAlign = 'center'; g.fillStyle = '#0b1400'; g.fillText('P' + (k + 1), p[0], p[1] + 5);
      });
    });
  }
  function setCam(i, silent) {
    activeCam = i;
    document.querySelectorAll('.camb').forEach((b) => b.setAttribute('aria-pressed', String(+b.dataset.cam === i)));
    const d = CAMS[i];
    $('cctvTag').textContent = d.name + ' Â· ' + d.sector; $('cctvCam').textContent = d.name; $('cctvSector').textContent = d.sector + (d.ptz ? ' Â· PTZ' : '');
    drawCamLayer();
    if (twin) twin.onCamChange();
    if (!silent) logEvent('CÃ¢mera ativa: ' + d.name + ' (' + d.sector + ').');
  }
  ['camselA', 'camselB'].forEach((id) => {
    CAMS.forEach((d, i) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'camb'; b.dataset.cam = String(i); b.textContent = '[' + d.name + ']';
      b.setAttribute('aria-pressed', 'false'); b.setAttribute('aria-label', 'CÃ¢mera ' + d.id + ', ' + d.sector);
      b.addEventListener('click', () => setCam(i));
      $(id).appendChild(b);
    });
  });
  document.addEventListener('keydown', (e) => {
    if (e.altKey || e.ctrlKey || e.metaKey || (e.target.closest && e.target.closest('input, textarea, select'))) return;
    const k = ['1', '2', '3'].indexOf(e.key);
    if (k >= 0 && $('viewer').offsetParent) setCam(k);
  });

  // ---------- Inicialização ----------
  // Desenha a planta de exemplo, sobe o gêmeo 3D e liga o laço de renderização
  // (detalhes em animate(), dentro de initTwin, na seção 8).
  drawSample();
  try {
    if (typeof THREE === 'undefined') throw new Error('Three.js nÃ£o carregou');
    twin = initTwin();
  } catch (err) {
    const msg = document.createElement('div');
    msg.className = 'nowebgl';
    msg.textContent = 'O visualizador 3D nÃ£o pÃ´de iniciar (' + err.message + '). A leitura da planta continua funcionando.';
    $('viewer').appendChild(msg);
    $('paintBtn').disabled = true; $('calibBtn').disabled = true;
    setBanner('idle', 'Visualizador 3D indisponÃ­vel', 'WebGL ou Three.js nÃ£o foram carregados neste navegador.');
  }
  setCam(0, true);
  processPlan('Planta de exemplo extrudada em BIM 3D');
})();


