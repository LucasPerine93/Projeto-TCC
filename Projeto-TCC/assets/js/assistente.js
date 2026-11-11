/* Painel do assistente de IA: consulta SOMENTE LEITURA sobre o SQLite do painel.
   Fluxo: POST /assistente { pergunta } -> { resposta, fatos, acao | null }.
   Se a resposta traz acao.tipo === "focar_gemeo", oferece o botão
   "Ver região no Gêmeo 3D" que abre a aba Gêmeo 3D com o mapa de calor ligado.
   O assistente nunca envia dados de escrita: apenas a pergunta (texto) e,
   quando houver LLM externo, os fatos agregados definidos no backend. */
import { lerPreferencia, gravarPreferencia } from "./util.js";
import { apiJson } from "./api.js";
import { irPara } from "./nucleo.js";

const botao = document.getElementById("botao-ia");
const painel = document.getElementById("painel-ia");
const fechar = document.getElementById("ia-fechar");
const form = document.getElementById("ia-form");
const entrada = document.getElementById("ia-entrada");
const enviar = form.querySelector('button[type="submit"]');
const historico = document.getElementById("ia-historico");
const exemplos = document.querySelectorAll(".ia-exemplo");

function abrir(sim, { foco = true, lembrar = true } = {}) {
  painel.hidden = !sim;
  botao.setAttribute("aria-expanded", String(sim));
  document.body.dataset.ia = sim ? "aberto" : "fechado";
  if (lembrar) gravarPreferencia("assistenteAberto", sim);
  if (foco) (sim ? fechar : botao).focus();
  if (sim) entrada.focus();
  // o gêmeo 3D e o vídeo se redimensionam sozinhos; o evento cobre navegadores sem ResizeObserver
  window.dispatchEvent(new Event("resize"));
}

botao.addEventListener("click", () => abrir(painel.hidden));
fechar.addEventListener("click", () => abrir(false));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !painel.hidden && painel.contains(document.activeElement)) abrir(false);
});

/* ---------------- Perguntas e respostas ---------------- */
function novaPergunta(texto) {
  historico.hidden = false;
  const li = document.createElement("article");
  li.className = "ia-dialogo ia-pendente";
  const pergunta = document.createElement("p");
  pergunta.className = "ia-pergunta";
  pergunta.textContent = texto;
  const resposta = document.createElement("p");
  resposta.className = "ia-resposta";
  resposta.textContent = "Consultando o banco…";
  const acoes = document.createElement("div");
  acoes.className = "ia-acoes";
  li.append(pergunta, resposta, acoes);
  historico.append(li);
  li.scrollIntoView({ block: "nearest" });
  return { li, resposta, acoes };
}

function concluir(entrada_ia, res) {
  entrada_ia.li.classList.remove("ia-pendente");
  entrada_ia.resposta.textContent = res.resposta;
  if (res.acao && res.acao.tipo === "focar_gemeo") {
    const acao = document.createElement("button");
    acao.type = "button";
    acao.className = "btn btn-pequeno btn-primario ia-acao";
    acao.textContent = "Ver região no Gêmeo 3D";
    acao.addEventListener("click", () => focarGemeo(res.acao.x_m, res.acao.z_m));
    entrada_ia.acoes.append(acao);
  }
}

function focarGemeo(x_m, z_m) {
  if (!Number.isFinite(Number(x_m)) || !Number.isFinite(Number(z_m))) return;
  irPara("gemeo");
  // o motor do gêmeo só carrega na 1ª visita à aba: espera o gancho surgir
  let tentativas = 0;
  const aguardar = setInterval(() => {
    if (window.gemeoFocarRegiao) {
      clearInterval(aguardar);
      window.gemeoFocarRegiao(Number(x_m), Number(z_m));
    } else if (++tentativas > 60) {
      clearInterval(aguardar);
    }
  }, 150);
}

async function perguntar(texto) {
  if (!texto || enviando) return;
  enviando = true;
  enviar.disabled = true;
  const item = novaPergunta(texto);
  try {
    const res = await apiJson("/assistente", { method: "POST", corpo: { pergunta: texto } });
    concluir(item, res);
  } catch (erro) {
    item.li.classList.add("ia-erro");
    item.resposta.textContent =
      erro.status === 401
        ? "Sessão expirada. Entre novamente para usar o assistente."
        : "Não foi possível consultar o assistente agora. Tente novamente.";
  } finally {
    enviando = false;
    enviar.disabled = false;
    entrada.focus();
  }
}

let enviando = false;

form.addEventListener("submit", (evento) => {
  evento.preventDefault();
  const texto = entrada.value.trim();
  if (!texto) return;
  entrada.value = "";
  perguntar(texto);
});

for (const exemplo of exemplos) {
  exemplo.addEventListener("click", () => {
    if (enviando) return;
    const texto = exemplo.dataset.pergunta || exemplo.textContent.trim();
    entrada.value = texto;
    form.requestSubmit();
  });
}

abrir(lerPreferencia("assistenteAberto") === "true" && window.innerWidth >= 1100, { foco: false, lembrar: false });