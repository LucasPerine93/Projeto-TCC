/* Tema claro (padrão, melhor ao sol) e escuro, lembrado neste navegador. */
import { lerPreferencia, gravarPreferencia } from "./util.js";

const botao = document.getElementById("botao-tema");

function aplicar(tema) {
  document.documentElement.dataset.tema = tema;
  const escuro = tema === "escuro";
  botao.setAttribute("aria-pressed", String(escuro));
  botao.setAttribute("aria-label", escuro ? "Usar tema claro" : "Usar tema escuro");
  botao.querySelector("use").setAttribute("href", `icones.svg#${escuro ? "sol" : "lua"}`);
}

aplicar(lerPreferencia("tema", "claro") === "escuro" ? "escuro" : "claro");

botao.addEventListener("click", () => {
  const proximo = document.documentElement.dataset.tema === "escuro" ? "claro" : "escuro";
  gravarPreferencia("tema", proximo);
  aplicar(proximo);
});
