/* =========================================================================
   tema.js — Tema claro/escuro do painel (preferência lembrada no navegador)
   -------------------------------------------------------------------------
   Controla: o data-attribute ``dataset.tema`` no <html>, o estado acessível do
   botão (#botao-tema: aria-pressed/aria-label/ícone sol-lua) e a persistência
   da preferência via util.js (lerPreferencia/gravarPreferencia).
   ========================================================================= */
/* Tema claro (padrão, melhor ao sol) e escuro, lembrado neste navegador. */
import { lerPreferencia, gravarPreferencia } from "./util.js";

/* ===== 1. BOTÃO #botao-tema e aplicação inicial da preferência ===== */
const botao = document.getElementById("botao-tema");

function aplicar(tema) {
  document.documentElement.dataset.tema = tema;
  const escuro = tema === "escuro";
  botao.setAttribute("aria-pressed", String(escuro));
  botao.setAttribute("aria-label", escuro ? "Usar tema claro" : "Usar tema escuro");
  botao.querySelector("use").setAttribute("href", `icones.svg#${escuro ? "sol" : "lua"}`);
}

aplicar(lerPreferencia("tema", "escuro") === "claro" ? "claro" : "escuro");

/* ===== 2. ALTERNÂNCIA DE TEMA AO CLICAR ===== */
botao.addEventListener("click", () => {
  const proximo = document.documentElement.dataset.tema === "escuro" ? "claro" : "escuro";
  gravarPreferencia("tema", proximo);
  aplicar(proximo);
});
