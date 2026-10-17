/* Tela "Ocorrências": fila de revisão, filtros, detalhes e exportação. */
import { apiJson, api } from "./api.js";
import {
  el, icone, infoTipo, pilulaTipo, pilulaStatus, ordemGravidade, TIPOS_CONHECIDOS, normalizar,
  dataHoraCompleta, dataHoraRelativa, inicioDoPeriodo, regiaoDoQuadro, formatarPercentual, plural,
} from "./util.js";
import { registrarTela, avisar } from "./nucleo.js";
import { agruparCenas, desenharCaixas, statusDe, resumoRevisao, mesmaCaixa } from "./cenas.js";

const TAMANHO_PAGINA = 30;

const lista = document.getElementById("lista-ocorrencias");
const resumo = document.getElementById("resumo-ocorrencias");
const botaoMais = document.getElementById("botao-mais");
const botaoAtualizar = document.getElementById("botao-atualizar");
const botaoExportar = document.getElementById("botao-exportar");
const filtroStatus = document.getElementById("filtro-status");
const filtroPeriodo = document.getElementById("filtro-periodo");
const filtroTipo = document.getElementById("filtro-tipo");
const avisoExportar = document.getElementById("aviso-exportar");
const selo = document.getElementById("selo-pendentes");

const filtros = { status: "pendente", periodo: "todos", tipo: null };
let ocorrencias = [];
let cenas = [];
let carregado = false;
let falhou = false;
let visiveis = TAMANHO_PAGINA;
let temporizador = null;

/* ---------- dados ---------- */
export const todasAsCenas = () => cenas;
export const jaCarregou = () => carregado;
export const cenasPendentes = () =>
  cenas.filter((c) => c.ocorrencias.some((o) => statusDe(o) === "pendente"))
    .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

export async function carregarOcorrencias() {
  try {
    const dados = await apiJson("/listar_ocorrencias");
    ocorrencias = Array.isArray(dados) ? dados : [];
    falhou = false;
  } catch {
    falhou = true;
  }
  carregado = true;
  cenas = agruparCenas(ocorrencias);
  atualizarSelo();
  if (!document.querySelector('[data-tela="ocorrencias"]').hidden) desenharLista();
  sincronizarDialogo();
  document.dispatchEvent(new CustomEvent("ocorrencias-atualizadas"));
}

function atualizarSelo() {
  const n = ocorrencias.filter((o) => statusDe(o) === "pendente").length;
  selo.hidden = n === 0;
  selo.textContent = n > 99 ? "99+" : String(n);
  selo.setAttribute("aria-label", `${n} pendentes de revisão`);
}

/* ---------- filtros ---------- */
function cenaPassa(cena, { ignorarTipo = false, ignorarStatus = false } = {}) {
  if (filtros.periodo !== "todos" && new Date(cena.timestamp) < inicioDoPeriodo(filtros.periodo)) return false;
  return cena.ocorrencias.some((o) =>
    (ignorarStatus || filtros.status === "todas" || statusDe(o) === filtros.status) &&
    (ignorarTipo || !filtros.tipo || infoTipo(o.tipo_infracao).rotulo === filtros.tipo));
}

function desenharFiltros() {
  // Contadores de status respeitam período e tipo.
  const contagem = { pendente: 0, confirmada: 0, descartada: 0, todas: 0 };
  cenas.forEach((c) => {
    if (filtros.periodo !== "todos" && new Date(c.timestamp) < inicioDoPeriodo(filtros.periodo)) return;
    const vistos = new Set();
    c.ocorrencias.forEach((o) => {
      if (filtros.tipo && infoTipo(o.tipo_infracao).rotulo !== filtros.tipo) return;
      vistos.add(statusDe(o));
    });
    if (vistos.size) contagem.todas += 1;
    vistos.forEach((s) => { contagem[s] += 1; });
  });
  filtroStatus.querySelectorAll("button").forEach((b) => {
    b.setAttribute("aria-pressed", String(b.dataset.valor === filtros.status));
    b.querySelector(".contador").textContent = carregado ? `(${contagem[b.dataset.valor]})` : "";
  });

  // Chips de tipo com contagem no recorte atual (status + período).
  const porTipo = new Map(TIPOS_CONHECIDOS.map((t) => [t, 0]));
  cenas.forEach((c) => {
    if (!cenaPassa(c, { ignorarTipo: true })) return;
    new Set(c.ocorrencias
      .filter((o) => filtros.status === "todas" || statusDe(o) === filtros.status)
      .map((o) => infoTipo(o.tipo_infracao).rotulo))
      .forEach((r) => porTipo.set(r, (porTipo.get(r) ?? 0) + 1));
  });
  const total = [...porTipo.values()].reduce((a, b) => a + b, 0);
  const chips = [["Todos os tipos", null, total]];
  [...porTipo.entries()]
    .sort((a, b) => ordemGravidade(infoTipo(a[0]).gravidade) - ordemGravidade(infoTipo(b[0]).gravidade))
    .forEach(([rotulo, n]) => { if (n > 0 || filtros.tipo === rotulo) chips.push([rotulo, rotulo, n]); });
  filtroTipo.replaceChildren(...chips.map(([texto, valor, n]) => el("button", {
    type: "button", "aria-pressed": String(filtros.tipo === valor),
    onclick: () => { filtros.tipo = valor; visiveis = TAMANHO_PAGINA; desenharLista(); },
  }, `${texto} (${n})`)));
}

function cenasFiltradas() {
  return cenas.filter((c) => cenaPassa(c)).sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
}

/* ---------- lista ---------- */
export function criarItemCena(cena, { aoAbrir, comAcoes = true } = {}) {
  const r = resumoRevisao(cena);
  const tipos = [...new Set(cena.ocorrencias.map((o) => o.tipo_infracao))]
    .sort((a, b) => ordemGravidade(infoTipo(a).gravidade) - ordemGravidade(infoTipo(b).gravidade));
  const estadoCena = r.pendente ? "pendente" : r.confirmada ? "confirmada" : "descartada";

  const miniatura = el("div", { class: "miniatura" },
    el("img", { src: `/foto/${cena.caminho_foto}`, alt: "", loading: "lazy" }));
  const meta = [dataHoraRelativa(cena.timestamp), plural(cena.total_registros, "trabalhador", "trabalhadores")];
  if (cena.total_registros > 1 && r.pendente !== cena.total_registros) meta.push(`${r.pendente} pendente(s)`);

  const principal = el("button", {
    class: "item-principal", type: "button", onclick: () => aoAbrir?.(cena),
    "aria-label": `Abrir ocorrência de ${dataHoraRelativa(cena.timestamp)}`,
  },
    miniatura,
    el("span", { class: "item-texto" },
      el("span", { class: "item-linha" }, tipos.map((t) => pilulaTipo(t)), pilulaStatus(estadoCena)),
      el("span", { class: "item-meta" }, meta.join(" · "))));

  const acoes = el("div", { class: "item-acoes" });
  if (comAcoes) {
    acoes.append(el("button", { class: "btn", type: "button", onclick: () => aoAbrir?.(cena) },
      r.pendente ? "Revisar" : "Ver detalhes"));
  }
  return el("div", { class: "item-oc" }, principal, acoes);
}

function desenharLista() {
  desenharFiltros();
  const alvo = cenasFiltradas();

  const pendentes = ocorrencias.filter((o) => statusDe(o) === "pendente").length;
  resumo.textContent = !carregado ? "Carregando…"
    : falhou ? "Não foi possível carregar as ocorrências."
    : `${plural(cenas.length, "foto registrada", "fotos registradas")} · ${plural(pendentes, "pendente de revisão", "pendentes de revisão")}`;

  lista.replaceChildren();
  if (falhou) {
    lista.append(el("p", { class: "vazio", role: "alert" }, "Sem resposta do servidor. Verifique a conexão e toque em Atualizar."));
  } else if (!alvo.length) {
    const nenhuma = !cenas.length;
    lista.append(el("p", { class: "vazio" }, nenhuma
      ? "Nenhuma ocorrência registrada ainda."
      : filtros.status === "pendente" && !filtros.tipo && filtros.periodo === "todos"
        ? "Tudo revisado. Não há ocorrências pendentes."
        : "Nenhuma ocorrência com esses filtros."));
  } else {
    alvo.slice(0, visiveis).forEach((c) => lista.append(criarItemCena(c, { aoAbrir: abrirDetalhe })));
  }
  botaoMais.hidden = alvo.length <= visiveis;
  botaoMais.textContent = `Mostrar mais (${alvo.length - visiveis})`;
}

botaoMais.addEventListener("click", () => { visiveis += TAMANHO_PAGINA; desenharLista(); });
botaoAtualizar.addEventListener("click", async () => {
  botaoAtualizar.disabled = true;
  await carregarOcorrencias();
  botaoAtualizar.disabled = false;
});
filtroStatus.addEventListener("click", (e) => {
  const b = e.target.closest("button[data-valor]");
  if (!b) return;
  filtros.status = b.dataset.valor; visiveis = TAMANHO_PAGINA; desenharLista();
});
filtroPeriodo.addEventListener("change", () => { filtros.periodo = filtroPeriodo.value; visiveis = TAMANHO_PAGINA; desenharLista(); });

/** Abre a lista já filtrada por situação (usado pelo Painel). */
export function filtrarPorStatus(status) { filtros.status = status; filtros.tipo = null; }

/* ---------- CSV ---------- */
function campoCsv(valor) {
  let texto = String(valor ?? "");
  if (/^[=+\-@\t\r]/.test(texto)) texto = `'${texto}`; // evita fórmulas ao abrir no Excel
  return `"${texto.replace(/"/g, '""')}"`;
}

botaoExportar.addEventListener("click", () => {
  const linhas = cenasFiltradas().flatMap((c) => c.ocorrencias)
    .filter((o) => (filtros.status === "todas" || statusDe(o) === filtros.status) &&
      (!filtros.tipo || infoTipo(o.tipo_infracao).rotulo === filtros.tipo));
  if (!linhas.length) {
    avisoExportar.hidden = false;
    avisoExportar.textContent = "Não há ocorrências para exportar com esses filtros.";
    return;
  }
  const cab = ["id", "data_hora", "tipo_infracao", "situacao", "motivo", "revisado_em", "conf_pessoa", "conf_capacete", "conf_colete", "foto"];
  const corpo = linhas.map((o) => [
    o.id, dataHoraCompleta(o.timestamp), infoTipo(o.tipo_infracao).rotulo, statusDe(o), o.motivo ?? "",
    o.revisado_em ?? "", o.conf_pessoa ?? "", o.conf_capacete ?? "", o.conf_colete ?? "", o.caminho_foto ?? "",
  ].map(campoCsv).join(";"));
  const blob = new Blob(["﻿" + [cab.join(";"), ...corpo].join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = el("a", { href: URL.createObjectURL(blob), download: `ocorrencias-${new Date().toISOString().slice(0, 10)}.csv` });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  avisoExportar.hidden = false;
  avisoExportar.textContent = `${plural(linhas.length, "ocorrência exportada", "ocorrências exportadas")} (${filtros.status === "todas" ? "todas as situações" : filtros.status}).`;
});

/* ---------- detalhes ---------- */
const dlg = document.getElementById("dialogo-detalhe");
const D = (id) => document.getElementById(id);
const moldura = D("foto-moldura");
const imagem = D("foto-ampliada");
const seletor = D("seletor-trabalhador");
const seletorBotoes = D("seletor-trabalhador-botoes");
const btnCaixas = D("btn-marcar-caixas");
const blocoMotivo = D("rev-motivo-bloco");

let aberta = null; // { chave, sel }  sel = -1 => todos
let marcacoes = true;

const cenaAberta = () => cenas.find((c) => c.chave === aberta?.chave) ?? null;
const entrada = (cena) => (aberta.sel >= 0 ? cena.selecionaveis[aberta.sel] : null);

function abrirDetalhe(cena) {
  const primeiro = cena.selecionaveis.findIndex((s) => statusDe(s.ocorrencia) === "pendente");
  aberta = { chave: cena.chave, sel: cena.selecionaveis.length > 1 && primeiro < 0 ? -1 : Math.max(primeiro, 0) };
  blocoMotivo.hidden = true;
  desenharDetalhe();
  if (!dlg.open) dlg.showModal();
}

function classeConf(v) { return v >= 0.7 ? "alta" : v >= 0.5 ? "media" : "baixa"; }
function barra(idBarra, idTexto, v) {
  const barraEl = D(idBarra), saida = D(idTexto);
  const n = v === null || v === undefined || Number.isNaN(Number(v)) || Number(v) === 0 ? null : Number(v);
  saida.title = n === null ? "Não detectado" : "";
  barraEl.className = n === null ? "" : classeConf(n);
  barraEl.style.width = n === null ? "0%" : `${Math.round(n * 100)}%`;
  saida.textContent = n === null ? "—" : `${Math.round(n * 100)}%`;
}

function desenharDetalhe() {
  const cena = cenaAberta();
  if (!cena) return;
  const multiplos = cena.selecionaveis.length > 1;
  const todos = aberta.sel < 0;
  const sel = entrada(cena);
  const oc = sel?.ocorrencia ?? null;
  const trab = sel?.trabalhador ?? null;

  D("det-titulo").textContent = `Ocorrência · ${dataHoraRelativa(cena.timestamp)}`;
  imagem.src = `/foto/${cena.caminho_foto}`;
  imagem.alt = `Foto da ocorrência de ${dataHoraCompleta(cena.timestamp)}`;
  D("det-data").textContent = dataHoraCompleta(cena.timestamp);

  // Seletor de trabalhadores
  seletor.hidden = !multiplos;
  seletorBotoes.replaceChildren();
  if (multiplos) {
    seletorBotoes.append(el("button", {
      type: "button", "aria-pressed": String(todos),
      onclick: () => { aberta.sel = -1; blocoMotivo.hidden = true; desenharDetalhe(); },
    }, `Todos (${cena.selecionaveis.length})`));
    cena.selecionaveis.forEach((s, i) => {
      const info = infoTipo(s.ocorrencia.tipo_infracao);
      seletorBotoes.append(el("button", {
        type: "button", "aria-pressed": String(aberta.sel === i),
        "aria-label": `Trabalhador ${i + 1}: ${info.rotulo}, ${statusDe(s.ocorrencia)}`,
        onclick: () => { aberta.sel = i; blocoMotivo.hidden = true; desenharDetalhe(); },
      }, icone(statusDe(s.ocorrencia) === "pendente" ? "lista" : statusDe(s.ocorrencia) === "confirmada" ? "ok" : "x"), `#${i + 1}`));
    });
  }

  // Caixas
  moldura.classList.toggle("marcacoes-ocultas", !marcacoes);
  btnCaixas.setAttribute("aria-pressed", String(marcacoes));
  D("texto-marcar-caixas").textContent = marcacoes ? "Ocultar marcações" : "Mostrar marcações";
  desenharCaixas(moldura, {
    trabalhadores: cena.trabalhadores, selecionaveis: cena.selecionaveis, total_registros: cena.total_registros,
    selecionado: aberta.sel, modoTodos: todos,
  }, { aoSelecionar: (i) => { aberta.sel = i; blocoMotivo.hidden = true; desenharDetalhe(); } });

  // Info
  const pilulas = D("det-pilulas");
  pilulas.replaceChildren();
  if (todos) {
    [...new Set(cena.ocorrencias.map((o) => o.tipo_infracao))].forEach((t) => pilulas.append(pilulaTipo(t)));
    D("det-escopo-rotulo").textContent = "Visão";
    D("det-escopo").textContent = `Panorama de ${cena.selecionaveis.length} trabalhadores`;
    D("det-regiao").textContent = "—";
    D("det-conf-titulo").textContent = "Selecione um trabalhador para ver a confiança";
    barra("barra-pessoa", "conf-pessoa", null); barra("barra-capacete", "conf-capacete", null); barra("barra-colete", "conf-colete", null);
  } else {
    pilulas.append(pilulaTipo(oc.tipo_infracao), pilulaStatus(statusDe(oc)));
    D("det-escopo-rotulo").textContent = "Trabalhador";
    D("det-escopo").textContent = multiplos ? `#${aberta.sel + 1} de ${cena.selecionaveis.length}` : "Único na foto";
    const p = trab?.pessoa;
    D("det-regiao").textContent = p ? regiaoDoQuadro((p[0] + p[2]) / 2) : "—";
    D("det-conf-titulo").textContent = "Confiança das detecções";
    barra("barra-pessoa", "conf-pessoa", trab?.conf_pessoa ?? oc.conf_pessoa);
    barra("barra-capacete", "conf-capacete", trab?.conf_capacete ?? oc.conf_capacete);
    barra("barra-colete", "conf-colete", trab?.conf_colete ?? oc.conf_colete);
  }

  // Revisão
  const st = oc ? statusDe(oc) : null;
  const pendentesCena = cena.ocorrencias.filter((o) => statusDe(o) === "pendente").length;
  const estadoTxt = D("det-rev-estado");
  if (todos) estadoTxt.textContent = `${pendentesCena} pendente(s) nesta foto. Escolha um trabalhador para revisar.`;
  else if (st === "pendente") estadoTxt.textContent = "Aguardando revisão.";
  else estadoTxt.textContent = `${st === "confirmada" ? "Infração confirmada" : "Marcada como falso positivo"}${oc.motivo ? `: ${oc.motivo}` : ""}${oc.revisado_em ? ` · ${dataHoraCompleta(oc.revisado_em)}` : ""}`;
  D("rev-confirmar").hidden = todos || st !== "pendente";
  D("rev-falso").hidden = todos || st !== "pendente";
  D("rev-reabrir").hidden = todos || st === "pendente";
  D("rev-todas").hidden = !(pendentesCena > 1);
}

btnCaixas.addEventListener("click", () => { marcacoes = !marcacoes; desenharDetalhe(); });
D("det-fechar").addEventListener("click", () => dlg.close());
dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
dlg.addEventListener("close", () => { aberta = null; });

function sincronizarDialogo() {
  if (!dlg.open || !aberta) return;
  if (!cenaAberta()) { dlg.close(); return; }
  const cena = cenaAberta();
  if (aberta.sel >= cena.selecionaveis.length) aberta.sel = Math.max(0, cena.selecionaveis.length - 1);
  desenharDetalhe();
}

async function enviarRevisao(o, status, motivo = "") {
  const q = new URLSearchParams({ status });
  if (motivo) q.set("motivo", motivo);
  const r = await api(`/revisar_ocorrencia/${encodeURIComponent(o.id)}?${q}`, { method: "POST" });
  if (r.status === 404 || r.status === 405) {
    avisar("Este servidor ainda não suporta revisão. Atualize o software da placa.", { tipo: "erro", duracao: 8000 });
    return false;
  }
  const dados = await r.json().catch(() => ({}));
  if (!r.ok || dados?.sucesso === false) {
    avisar(dados?.mensagem || "Não foi possível salvar a revisão.", { tipo: "erro" });
    return false;
  }
  o.status = status;
  o.motivo = status === "descartada" ? motivo : status === "pendente" ? null : (o.motivo ?? null);
  o.revisado_em = status === "pendente" ? null : new Date().toISOString();
  return true;
}

async function aposRevisao(textoOk) {
  cenas = agruparCenas(ocorrencias);
  atualizarSelo();
  desenharLista();
  const cena = cenaAberta();
  if (cena && aberta.sel >= 0) {
    const prox = cena.selecionaveis.findIndex((s) => statusDe(s.ocorrencia) === "pendente");
    if (prox >= 0) aberta.sel = prox;
  }
  blocoMotivo.hidden = true;
  desenharDetalhe();
  avisar(textoOk, { tipo: "ok", duracao: 2500 });
  document.dispatchEvent(new CustomEvent("ocorrencias-atualizadas"));
}

async function revisarAtual(status, motivo = "") {
  const cena = cenaAberta(); const sel = cena && entrada(cena);
  if (!sel) return;
  if (await enviarRevisao(sel.ocorrencia, status, motivo)) {
    await aposRevisao(status === "confirmada" ? "Infração confirmada." : status === "descartada" ? "Marcada como falso positivo." : "Reaberta para revisão.");
  }
}

D("rev-confirmar").addEventListener("click", () => revisarAtual("confirmada"));
D("rev-reabrir").addEventListener("click", () => revisarAtual("pendente"));
D("rev-falso").addEventListener("click", () => {
  blocoMotivo.hidden = false;
  D("rev-falso").setAttribute("aria-expanded", "true");
  blocoMotivo.querySelector('input[type="radio"]:checked')?.focus();
});
D("rev-falso-cancelar").addEventListener("click", () => { blocoMotivo.hidden = true; D("rev-falso").setAttribute("aria-expanded", "false"); });
D("rev-falso-ok").addEventListener("click", () => {
  const base = blocoMotivo.querySelector('input[name="motivo"]:checked')?.value ?? "";
  const obs = D("rev-obs").value.trim();
  D("rev-obs").value = "";
  D("rev-falso").setAttribute("aria-expanded", "false");
  revisarAtual("descartada", obs ? `${base} — ${obs}` : base);
});
D("rev-todas").addEventListener("click", async () => {
  const cena = cenaAberta();
  if (!cena) return;
  let n = 0;
  for (const o of cena.ocorrencias.filter((x) => statusDe(x) === "pendente")) {
    if (await enviarRevisao(o, "confirmada")) n += 1; else break;
  }
  if (n) await aposRevisao(`${plural(n, "infração confirmada", "infrações confirmadas")}.`);
});

/* ---------- ciclo de vida ---------- */
document.addEventListener("nova-ocorrencia", () => { if (carregado) carregarOcorrencias(); });

export function iniciarOcorrencias() {
  carregarOcorrencias();
  window.clearInterval(temporizador);
  temporizador = window.setInterval(() => { if (!document.hidden) carregarOcorrencias(); }, 30000);
}
export function pararOcorrencias() {
  window.clearInterval(temporizador);
  carregado = false; ocorrencias = []; cenas = []; atualizarSelo();
  if (dlg.open) dlg.close();
}

registrarTela("ocorrencias", { entrar: () => { desenharLista(); if (carregado) carregarOcorrencias(); } });
export { abrirDetalhe };
