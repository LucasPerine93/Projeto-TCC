/* Acesso. Prefere a sessão por cookie (POST /login, GET /sessao). Se o servidor ainda
   não tem essas rotas (404/405), cai no fluxo antigo: evento "senha" pelo socket. */
import { ui } from "./conexao_ui.js";
import { api } from "./api.js";
import { estado, mostrarBloqueio } from "./nucleo.js";

const form = document.getElementById("form-login");
const campo = document.getElementById("campo-senha");
const erro = document.getElementById("erro-login");
const botao = document.getElementById("botao-entrar");

let aoEntrar = () => {};
let aoSair = () => {};
let temporizadorErro = null;

function mostrarErro(texto, ms = 4000) {
  erro.textContent = texto;
  window.clearTimeout(temporizadorErro);
  if (texto && ms) temporizadorErro = window.setTimeout(() => { erro.textContent = ""; }, ms);
}

function ocupado(sim) {
  botao.disabled = sim;
  botao.textContent = sim ? "Entrando…" : "Entrar";
}

function liberar() {
  estado.autenticado = true;
  ocupado(false);
  campo.value = "";
  mostrarErro("");
  mostrarBloqueio(false);
  aoEntrar();
}

export function bloquear(mensagem = "") {
  estado.autenticado = false;
  ocupado(false);
  mostrarBloqueio(true);
  mostrarErro(mensagem, 0);
  campo.focus();
  aoSair();
}

function entrarPeloSocket(senha) {
  // O servidor antigo compara com um inteiro.
  const valor = /^\d+$/.test(senha) ? parseInt(senha, 10) : senha;
  ui.send_message("senha", { senha: valor });
}

form.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const senha = campo.value;
  if (!senha) { mostrarErro("Digite a senha para entrar."); campo.focus(); return; }
  ocupado(true);
  try {
    const r = await api("/login", { method: "POST", corpo: { senha } });
    if (r.ok) {
      const dados = await r.json().catch(() => ({}));
      if (dados?.ticket) ui.send_message("auth", { ticket: dados.ticket });
      liberar();
    } else if (r.status === 404 || r.status === 405) {
      entrarPeloSocket(senha);
    } else if (r.status === 429) {
      const dados = await r.json().catch(() => ({}));
      ocupado(false);
      mostrarErro(dados?.mensagem || "Muitas tentativas. Aguarde um pouco e tente de novo.", 8000);
    } else {
      ocupado(false);
      campo.select();
      mostrarErro("Senha incorreta. Tente novamente.");
    }
  } catch {
    // Sem rota HTTP alcançável: tenta o fluxo antigo.
    entrarPeloSocket(senha);
  }
});

ui.on_message("liberado", () => liberar());
ui.on_message("rejeitado", () => {
  ocupado(false);
  campo.select();
  mostrarErro("Senha incorreta. Tente novamente.");
});

document.addEventListener("sessao-expirada", () => {
  if (estado.autenticado) bloquear("Sua sessão expirou. Entre novamente.");
});

export async function sair() {
  try { await api("/logout", { method: "POST" }); } catch { /* servidor antigo */ }
  bloquear("");
}

/** Chamado uma vez pelo app: restaura a sessão, se houver. */
export async function iniciarAcesso({ entrou, saiu }) {
  aoEntrar = entrou;
  aoSair = saiu;
  mostrarBloqueio(true);
  try {
    const r = await api("/sessao");
    if (r.ok) { liberar(); return; }
  } catch { /* sem rota de sessão */ }
  campo.focus();
}
