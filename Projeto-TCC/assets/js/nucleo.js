/* Estado compartilhado, navegação entre as telas e avisos (toasts). */
import { el, icone } from "./util.js";

export const estado = { tela: null, autenticado: false };

const telas = new Map();
const TITULOS = { "ao-vivo": "Ao vivo", ocorrencias: "Ocorrências", painel: "Painel" };

export function registrarTela(nome, { entrar } = {}) {
  telas.set(nome, { entrar });
}

export function telaDoHash() {
  return location.hash.replace(/^#\//, "");
}

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
  document.title = `${TITULOS[nome] ?? "Painel"} · Painel de EPIs`;

  if (historico && telaDoHash() !== nome) history.pushState(null, "", `#/${nome}`);
  telas.get(nome).entrar?.();
  if (foco) document.getElementById("conteudo")?.focus({ preventScroll: true });
}

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
}

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
