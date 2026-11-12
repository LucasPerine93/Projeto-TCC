/* =========================================================================
   interface.js — Interface do Gêmeo 3D (abas laterais, PiP do CCTV, espelhos)
   -------------------------------------------------------------------------
   Controla a camada de UI do gêmeo: abas por tecla/toque (plan/log/workers),
   contadores com MutationObserver (eventos/operários), espelhos de leitura
   (os mesmos valores aparecem na sidebar e no resumo), painel lateral
   colapsável, PiP do monitor CCTV (min/mid/max, teatro automático em celular
   e ao calibrar/pintando risco) e restauração do estado salvo no localStorage.
   NÃO altera a lógica do motor 3D (metadata = #viewer / canvas do Three.js).

   Índice de seções:
   1. Abas laterais e navegação por teclado
   2. Contadores de eventos e de operários (MutationObserver)
   3. Espelhos de leitura (KPI -> resumo)
   4. Painel lateral e PiP do CCTV (min/mid/max, teatro automático)
   ========================================================================= */
/* UI v7.0: abas, painel lateral, PiP do CCTV e espelhos de leitura. Não altera a lógica do gêmeo digital. */
(function () {
  // ===== 1. ABAS LATERAIS (abas e navegação por teclado) =====
  const $ = (id) => document.getElementById(id);
  const shell = $('shell'), pip = $('pip');
  const store = {
    get(k, d) { try { return localStorage.getItem('epi.gemeo.' + k) || d; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('epi.gemeo.' + k, v); } catch (e) { /* sem armazenamento */ } },
  };
  // Três.js já observa o #viewer; o evento extra cobre navegadores sem ResizeObserver e garante canvases corretos após a transição.
  const nudge = () => { window.dispatchEvent(new Event('resize')); setTimeout(() => window.dispatchEvent(new Event('resize')), 280); };

  // ---- abas ----
  const tabs = Array.from(document.querySelectorAll('.tab'));
  let unread = 0;
  function showTab(name, focus) {
    tabs.forEach((t) => {
      const on = t.dataset.pane === name;
      t.setAttribute('aria-selected', String(on)); t.tabIndex = on ? 0 : -1;
      $('pane-' + t.dataset.pane).hidden = !on;
      if (on && focus) t.focus();
    });
    if (name === 'log') { unread = 0; renderBadge(); }
    store.set('tab', name);
    nudge();
  }
  tabs.forEach((t, i) => {
    t.addEventListener('click', () => showTab(t.dataset.pane));
    t.addEventListener('keydown', (e) => {
      const k = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (k) { e.preventDefault(); showTab(tabs[(i + k + tabs.length) % tabs.length].dataset.pane, true); }
    });
  });

  // ===== 2. CONTADORES DE EVENTOS E DE OPERÁRIOS =====
  // ---- contadores de eventos e operários ----
  let total = document.querySelectorAll('#log li:not(.empty)').length, lastKey = '';
  const newest = () => { const li = $('log').querySelector('li:not(.empty)'); return li ? li.textContent : ''; };
  lastKey = newest();
  function renderBadge() {
    const b = $('tabLCount'); b.textContent = total; b.classList.toggle('new', unread > 0);
    $('evTotal').textContent = total;
  }
  new MutationObserver(() => {
    const k = newest();
    if (k && k !== lastKey) {
      lastKey = k; total++;
      if ($('pane-log').hidden) unread++;
      renderBadge();
    }
  }).observe($('log'), { childList: true });
  renderBadge();
  // só conta as vagas ocupadas: o pool de avatares do modo real tem mais chips do que operários visíveis
  const wc = () => { $('tabWCount').textContent = $('workers').querySelectorAll('.wchip:not([hidden])').length; };
  new MutationObserver(wc).observe($('workers'), { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden'] }); wc();

  // ===== 3. ESPELHOS DE LEITURA (a lógica original continua escrevendo nos ids originais) =====
  // ---- espelhos (a lógica original continua escrevendo nos ids originais) ----
  function mirror(src, dst) {
    const s = $(src), d = $(dst), f = () => { d.textContent = s.textContent; };
    new MutationObserver(f).observe(s, { childList: true, characterData: true, subtree: true }); f();
  }
  mirror('wallCount', 'wallCountM'); mirror('confVal', 'sumVal'); mirror('confStatus', 'sumStatus'); mirror('confAux', 'sumAux');
  const confCard = $('confCard'), sumCard = $('sumCard'), confFill = $('confFill');
  const syncConf = () => { sumCard.dataset.state = confCard.dataset.state || 'none'; $('sumFill').style.width = confFill.style.width || '0%'; };
  new MutationObserver(syncConf).observe(confCard, { attributes: true, attributeFilter: ['data-state'] });
  new MutationObserver(syncConf).observe(confFill, { attributes: true, attributeFilter: ['style'] }); syncConf();

  // ===== 4. PAINEL LATERAL E PiP DO CCTV (min/mid/max) =====
  // ---- painel lateral ----
  function setSide(open, temporario) {
    shell.dataset.side = open ? 'open' : 'closed';
    $('sideToggle').setAttribute('aria-expanded', String(open));
    if (!temporario) store.set('side', open ? 'open' : 'closed');
    nudge();
  }
  $('sideToggle').addEventListener('click', () => setSide(shell.dataset.side === 'closed'));

  // ---- PiP ----
  let autoMax = false, prevSize = 'mid';
  const celular = window.matchMedia('(max-width: 900px)');
  let lateralFechadaPeloPip = false;
  function setPip(size) {
    pip.dataset.size = size; store.set('pip', size);
    // no celular, o modo teatro libera a altura toda para o monitor e devolve a sidebar ao sair
    if (celular.matches && size === 'max' && shell.dataset.side !== 'closed') { lateralFechadaPeloPip = true; setSide(false, true); }
    else if (size !== 'max' && lateralFechadaPeloPip) { lateralFechadaPeloPip = false; setSide(true, true); }
    $('pipMin').setAttribute('aria-pressed', String(size === 'min'));
    $('pipMid').setAttribute('aria-pressed', String(size === 'mid'));
    $('pipMax').setAttribute('aria-pressed', String(size === 'max'));
    nudge();
  }
  $('pipMin').addEventListener('click', () => { autoMax = false; setPip('min'); });
  $('pipMid').addEventListener('click', () => { autoMax = false; setPip('mid'); });
  $('pipMax').addEventListener('click', () => { autoMax = false; setPip(pip.dataset.size === 'max' ? 'mid' : 'max'); });
  pip.querySelector('.pip-head').addEventListener('dblclick', (e) => { if (!e.target.closest('button')) setPip(pip.dataset.size === 'max' ? 'mid' : 'max'); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && pip.dataset.size === 'max') { autoMax = false; setPip('mid'); } });
  // Pintar risco ou calibrar pela câmera pede precisão: abre o modo teatro e devolve o tamanho anterior ao terminar.
  function editing() { return $('paintBtn').getAttribute('aria-pressed') === 'true' || $('calibBtn').getAttribute('aria-pressed') === 'true'; }
  function syncEdit() {
    if (editing() && pip.dataset.size !== 'max') { prevSize = pip.dataset.size; autoMax = true; setPip('max'); }
    else if (!editing() && autoMax) { autoMax = false; setPip(prevSize === 'min' ? 'mid' : prevSize); }
  }
  // observa o atributo para também restaurar quando a calibração termina sozinha após o 4º ponto
  ['paintBtn', 'calibBtn'].forEach((id) => new MutationObserver(syncEdit).observe($(id), { attributes: true, attributeFilter: ['aria-pressed'] }));

  // estado salvo
  const sp = store.get('pip', window.matchMedia('(max-width: 900px)').matches ? 'min' : 'mid'); setPip(sp === 'max' ? 'mid' : sp);
  showTab(store.get('tab', 'plan'));
  if (store.get('side', 'open') === 'closed') setSide(false);
})();
