// Testes da camada de adaptação de dados do Gêmeo 3D. Executar: node tests/js/test_fonte_dados.js
const assert = require('assert');
const modulo = require('../../assets/js/gemeo/fonte_dados.js');
// O adaptador é UMD: em uma árvore marcada como ESM ele publica a API no global,
// enquanto no CommonJS puro usa module.exports. Os testes aceitam os dois contextos.
const F = modulo.normalizarMensagem ? modulo : globalThis.GemeoFonte;
let n = 0; const t = (nome, fn) => { fn(); n++; console.log('ok -', nome); };

t('formato plano da v7', () => {
  const r = F.normalizarMensagem('{"id":"OP-01","x":3.5,"z":-2,"capacete":true,"colete":false,"inRisk":false}', 100);
  const w = r.frame.workers[0];
  assert.deepStrictEqual(w.position, { x: 3.5, z: -2 }); assert.strictEqual(w.status, 'violation'); assert.strictEqual(r.frame.source, 'real');
});
t('formato proposto com position/ppe/confidence', () => {
  const r = F.normalizarMensagem({ sequence: 5, timestamp: 90, workers: [{ id: 'w1', position: { x: 1, z: 2 }, ppe: { helmet: true, vest: true }, confidence: { person: 0.98, helmet: 1.4 }, riskZoneIds: [] }] }, 100);
  const w = r.frame.workers[0]; assert.strictEqual(w.status, 'safe'); assert.strictEqual(w.confidence.helmet, 1); assert.strictEqual(r.frame.sequence, 5);
});
t('formato nativo do detector (sem posição na planta)', () => {
  const r = F.normalizarMensagem({ workers: [{ track_id: 7, box_xyxy: [100, 50, 200, 400], tem_capacete: true, tem_colete: false, risco_detectado: true, conf_pessoa: 0.9 }] }, 1);
  const w = r.frame.workers[0]; assert.strictEqual(w.position, null); assert.deepStrictEqual(w.image.foot, [150, 400]); assert.strictEqual(w.status, 'risk'); assert.strictEqual(w.id, '7');
});
t('PPE ausente = desconhecido, não infração', () => {
  const w = F.normalizarMensagem({ id: 'a', x: 0, z: 0 }, 1).frame.workers[0]; assert.strictEqual(w.status, 'unknown'); assert.strictEqual(w.ppe.helmet, null);
});
t('rejeita lixo sem inventar dados', () => {
  assert.strictEqual(F.normalizarMensagem('{quebrado', 1).frame, null);
  assert.strictEqual(F.normalizarMensagem({ foo: 1 }, 1).frame, null);
  const r = F.normalizarMensagem({ workers: [{ id: 'a', x: 'abc', z: 1 }, null, { x: 1, z: 1 }] }, 1);
  assert.strictEqual(r.frame.workers.length, 1); assert.strictEqual(r.frame.workers[0].position, null); assert.strictEqual(r.invalidos, 2);
});
t('lista vazia é um quadro válido (ninguém na cena)', () => { assert.strictEqual(F.normalizarMensagem({ workers: [] }, 1).frame.workers.length, 0); });
t('ids repetidos e excesso de trabalhadores', () => {
  const many = Array.from({ length: 40 }, (_, i) => ({ id: i, x: 0, z: 0 }));
  assert.strictEqual(F.normalizarMensagem(many, 1).frame.workers.length, 32);
  assert.strictEqual(F.normalizarMensagem([{ id: 1, x: 0, z: 0 }, { id: 1, x: 1, z: 1 }], 1).frame.workers.length, 1);
});

t('fonte: estados, sequência e quadro mais recente', () => {
  let agora = 1000; const estados = [];
  const f = F.criarFonte({ relogio: () => agora, aoMudarEstado: (s) => estados.push(s.estado), staleMs: 3000 });
  f.usarCanal('painel', true);
  assert.strictEqual(f.estado().estado, 'aguardando');
  assert.ok(f.receber({ sequence: 10, workers: [{ id: 'a', x: 1, z: 1 }] }));
  assert.ok(!f.receber({ sequence: 10, workers: [] }), 'repetido');
  assert.ok(!f.receber({ sequence: 9, workers: [] }), 'fora de ordem');
  assert.ok(f.receber({ sequence: 11, workers: [{ id: 'a', x: 2, z: 2 }] }));
  assert.strictEqual(f.consumir().workers[0].position.x, 2); assert.strictEqual(f.consumir(), null);
  assert.strictEqual(f.estado().descartados, 2);
  agora += 3500; f.verificar(); assert.strictEqual(f.estado().estado, 'sem-sinal');
  f.receber({ sequence: 12, workers: [] }); assert.strictEqual(f.estado().estado, 'ativa');
  f.canalConectou(false); assert.strictEqual(f.estado().estado, 'desconectada'); assert.strictEqual(f.consumir(), null);
  f.canalConectou(true); assert.strictEqual(f.estado().estado, 'aguardando');
  f.parar(); assert.strictEqual(f.estado().estado, 'inativa');
});
t('fonte: reinício do servidor (sequência volta a 0) é aceito', () => {
  const f = F.criarFonte({ relogio: () => 1 }); f.usarCanal('painel', true);
  f.receber({ sequence: 5000, workers: [] }); assert.ok(f.receber({ sequence: 1, workers: [] }));
  f.parar();
});
t('fonte: WebSocket com falha reconecta e não cai para simulação', () => {
  const socks = []; const timers = [];
  const f = F.criarFonte({ criarSocket: (u) => { const s = { url: u, close() {} }; socks.push(s); return s; }, atrasosReconexao: [10] });
  assert.ok(!f.conectarWS('http://x'), 'rejeita esquema inválido'); assert.strictEqual(f.estado().estado, 'erro');
  assert.ok(f.conectarWS('ws://localhost:8000/ws')); assert.strictEqual(f.estado().estado, 'conectando');
  socks[0].onopen(); assert.strictEqual(f.estado().estado, 'aguardando');
  socks[0].onmessage({ data: '{"id":"a","x":1,"z":1}' }); assert.strictEqual(f.estado().estado, 'ativa');
  socks[0].onclose(); assert.strictEqual(f.estado().estado, 'desconectada');
  f.parar();
});
console.log(n + ' testes passaram'); process.exit(0);
