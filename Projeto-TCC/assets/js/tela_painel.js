/* Tela "Painel": conformidade = pessoas-frame conformes / pessoas-frame observadas. */
import { apiJson } from "./api.js";
import { el, icone, infoTipo, ordemGravidade, formatarPercentual, plural } from "./util.js";
import { registrarTela, irPara } from "./nucleo.js";
import { desenharLinha } from "./grafico.js";
import { cenasPendentes, criarItemCena, abrirDetalhe, carregarOcorrencias, jaCarregou, filtrarPorStatus } from "./tela_ocorrencias.js";

const META = 95;
const LIMITE_CRITICO = 85;

const seg = document.getElementById("painel-periodo");
const $ = (id) => document.getElementById(id);
let dias = 7;
let dados = null;
let erro = false;

const numero = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? null : Number(v));
const situacao = (v) => (v === null ? "neutro" : v >= META ? "ok" : v >= LIMITE_CRITICO ? "atencao" : "critico");
const TEXTO_SIT = { ok: "Dentro da meta", atencao: "Atenção", critico: "Crítico", neutro: "Sem dados" };
const ICONE_SIT = { ok: "ok", atencao: "aviso", critico: "x", neutro: "relogio" };
const NOME_PERIODO = { 1: "hoje", 7: "nos últimos 7 dias", 30: "nos últimos 30 dias" };

export async function carregarPainel() {
  try {
    dados = await apiJson(`/dashboard_dados?dias=${dias}`);
    erro = false;
  } catch { erro = true; }
  desenhar();
}

function dataCurta(iso) { const [, m, d] = iso.split("-"); return `${d}/${m}`; }

function serieCompleta() {
  const p = dados?.periodo;
  if (!p?.desde || !p?.ate || !Array.isArray(dados.serie_diaria)) return null;
  const mapa = new Map(dados.serie_diaria.map((s) => [s.dia, numero(s.conformidade)]));
  const pontos = [];
  for (let d = new Date(`${p.desde}T12:00:00`); d <= new Date(`${p.ate}T12:00:00`); d.setDate(d.getDate() + 1)) {
    const iso = d.toISOString().slice(0, 10);
    pontos.push({ rotulo: dataCurta(iso), valor: mapa.has(iso) ? mapa.get(iso) : null });
  }
  return pontos;
}

function desenhar() {
  $("painel-atualizado").textContent = erro ? "Não foi possível carregar os dados." : `Atualizado às ${new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
  seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.dias) === dias)));

  const conf = numero(dados?.conformidade);
  const pessoas = numero(dados?.pessoas_observadas) ?? 0;
  const sit = situacao(conf);

  $("conf-valor").replaceChildren(conf === null ? "—" : String(conf.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })), conf === null ? "" : el("small", {}, "%"));
  const s = $("conf-situacao");
  s.className = `situacao s-${sit}`;
  s.replaceChildren(icone(ICONE_SIT[sit]), conf === null ? TEXTO_SIT.neutro : `${TEXTO_SIT[sit]} · meta ${META}%`);

  const ant = numero(dados?.anterior?.conformidade);
  const t = $("conf-tendencia");
  if (conf !== null && ant !== null) {
    const dif = Math.round((conf - ant) * 10) / 10;
    t.textContent = dif === 0 ? "Igual ao período anterior" : `${dif > 0 ? "▲" : "▼"} ${Math.abs(dif).toLocaleString("pt-BR")} p.p. em relação ao período anterior`;
  } else t.textContent = conf === null ? "Sem observações no período. Nenhuma pessoa foi acompanhada." : "";

  $("conf-base").textContent = conf === null ? "" :
    `Base: ${pessoas.toLocaleString("pt-BR")} observações de pessoas (${plural(dados.trilhas ?? 0, "pessoa distinta", "pessoas distintas")}) ${NOME_PERIODO[dias]}.`;

  // Taxas
  const taxas = [["Capacete", numero(dados?.capacete)], ["Colete", numero(dados?.colete)], ["Fora da área de risco", numero(dados?.fora_de_risco)]];
  $("lista-taxas").replaceChildren(...taxas.map(([nome, v]) => {
    const c = situacao(v);
    return el("div", { class: "taxa" },
      el("span", {}, nome),
      el("div", { class: "barra", role: "img", "aria-label": `${nome}: ${v === null ? "sem dados" : formatarPercentual(v)}, meta ${META}%` },
        el("i", { class: c === "neutro" ? "" : c, style: `width:${v ?? 0}%` }), el("span", { class: "meta", style: `left:${META}%` })),
      el("output", {}, v === null ? "—" : formatarPercentual(v)));
  }));
  $("legenda-taxas").textContent = dados && numero(dados.fora_de_risco) === null
    ? "“Fora da área de risco” aparece como — quando não há área de risco definida."
    : `A linha marca a meta de ${META}%.`;

  // Gráfico
  const pontos = serieCompleta();
  const mostra = dias > 1 && pontos && pontos.some((p) => p.valor !== null);
  $("grafico").hidden = !mostra;
  $("grafico-vazio").hidden = mostra;
  $("grafico-vazio").textContent = dias === 1 ? "Para ver a evolução, escolha 7 ou 30 dias." : "Sem dados de conformidade no período.";
  if (mostra) desenharLinha($("grafico"), pontos, { meta: META });

  // Tipos
  const tipos = Object.entries(dados?.infracoes_por_tipo ?? dados?.resumo_conformidade ?? {})
    .filter(([t]) => infoTipo(t).gravidade !== "ok")
    .sort((a, b) => b[1] - a[1]);
  const maior = Math.max(1, ...tipos.map(([, n]) => n));
  $("lista-tipos").replaceChildren(...(tipos.length ? tipos.map(([tipo, n]) => {
    const info = infoTipo(tipo);
    return el("div", { class: "tipo" }, el("span", {}, info.rotulo), el("output", {}, String(n)),
      el("div", { class: "barra" }, el("i", { class: info.gravidade === "neutro" ? "" : info.gravidade, style: `width:${(n / maior) * 100}%` })));
  }) : [el("p", { class: "vazio" }, "Nenhuma ocorrência no período.")]));

  desenharFila();
}

function desenharFila() {
  const fila = $("fila-pendentes");
  const pend = cenasPendentes();
  $("ver-todas").hidden = pend.length === 0;
  $("ver-todas").textContent = `Ver todas (${pend.length})`;
  fila.replaceChildren(...(pend.length
    ? pend.slice(0, 3).map((c) => criarItemCena(c, { aoAbrir: abrirDetalhe }))
    : [el("p", { class: "vazio" }, jaCarregou() ? "Nada aguardando revisão." : "Carregando…")]));
}

seg.addEventListener("click", (e) => {
  const b = e.target.closest("button[data-dias]");
  if (!b) return;
  dias = Number(b.dataset.dias);
  carregarPainel();
});
$("ver-todas").addEventListener("click", () => { filtrarPorStatus("pendente"); irPara("ocorrencias"); });
document.addEventListener("ocorrencias-atualizadas", () => {
  if (!document.querySelector('[data-tela="painel"]').hidden) { desenharFila(); carregarPainel(); }
});
window.addEventListener("resize", () => { if (dados && !document.querySelector('[data-tela="painel"]').hidden) desenhar(); });

registrarTela("painel", {
  entrar: () => { carregarPainel(); if (!jaCarregou()) carregarOcorrencias(); else desenharFila(); },
});
