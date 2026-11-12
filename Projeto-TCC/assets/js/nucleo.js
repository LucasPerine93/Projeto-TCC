/* =========================================================================
   nucleo.js — Roteamento de abas, estado global e ciclo de vida das telas
   -------------------------------------------------------------------------
   Controla:
   - ``estado`` compartilhado (tela atual, autenticado) e o mapa
     registrarTela(nome, { entrar }) de cada tela;
   - navegação por abas/hash (#/painel etc.) com histórico do navegador
     (popstate) e foco no conteúdo;
   - mostrar/ocultar o bloco de acesso vs. o app;
   - chips de status (cheio = ok/alerta/erro) e o aviso (toast) temporário.
   ========================================================================= */
/* ===== 1. ESTADO GLOBAL E CATÁLOGO DE TELAS ===== */
import { el, icone } from "./util.js";

export const estado = { tela: null, autenticado: false };

const telas = new Map();
const TITULOS = { "ao-vivo": "Ao vivo", ocorrencias: "Ocorrências", painel: "Painel", gemeo: "Gêmeo 3D" };

export function registrarTela(nome, { entrar } = {}) {
  telas.set(nome, { entrar });
}

export function telaDoHash() {
  return location.hash.replace(/^#\//, "");
}

/* ===== 2. NAVEGAÇÃO E CICLO DE VIDA DAS TELAS ===== */
export function irPara(nome, { historico = true, foco = true } = {}) {
  if (!telas.has(nome)) nome = "ao-vivo";
  estado.tela = nome;

  document.querySelectorAll(".tela").forEach((secao) => {
    secao.hidden = secao.dataset.tela !== nome;
  });
  document.querySelectorAll("#abas [data-tela]").forEach((botao) => {
    if (botao.dataset.tela === nome) botao.setAttribute("aria-current", "page");
    else botao.removeAttribute("aria-current");
  });
  document.body.dataset.tela = nome;
  document.title = `${TITULOS[nome] ?? "Painel"} · Painel de EPIs`;

  if (historico && telaDoHash() !== nome) history.pushState(null, "", `#/${nome}`);
  telas.get(nome).entrar?.();
  if (foco) document.getElementById("conteudo")?.focus({ preventScroll: true });
}

/* ===== 3. BLOQUEIO DE ACESSO E CHIPS DE STATUS ===== */
window.addEventListener("popstate", () => {
  if (estado.autenticado) irPara(telaDoHash(), { historico: false });
});

/** Mostra a tela de acesso (true) ou a aplicação (false). */
export function mostrarBloqueio(sim) {
  document.getElementById("tela-bloqueio").hidden = !sim;
  document.getElementById("app").hidden = sim;
}

export function definirChip(id, situacao, texto) {
  const chip = document.getElementById(id);
  if (!chip) return;
  chip.dataset.estado = situacao;
  chip.querySelector("span").textContent = texto;
  chip.title = texto;               // na faixa de ícones o texto some; o tooltip e o leitor de tela mantêm a informação
}

/* ===== 4. AVISO (TOAST) TEMPORÁRIO ===== */
/** Aviso temporário. `acao` = { rotulo, aoClicar } (por exemplo "Desfazer"). */
export function avisar(texto, { tipo = "info", acao = null, duracao = 6000 } = {}) {
  const area = document.getElementById("avisos");
  const caixa = el("div", { class: `aviso aviso-${tipo}`, role: tipo === "erro" ? "alert" : "status" },
    icone(tipo === "erro" ? "aviso" : tipo === "ok" ? "ok" : "alerta"),
    el("span", {}, texto));
  const remover = () => caixa.remove();
  if (acao) {
    caixa.append(el("button", {
      class: "btn btn-pequeno", type: "button",
      onclick: () => { acao.aoClicar(); remover(); },
    }, acao.rotulo));
  }
  area.append(caixa);
  if (duracao > 0) window.setTimeout(remover, duracao);
  return remover;
}
