/* Painel do assistente de IA: SOMENTE a estrutura visual (abrir/fechar, acessível por teclado).
   Não há modelo, nem chamada de rede, nem resposta simulada. Pontos de integração futuros (ver PLANO_EVOLUCAO.md):
     - contexto de leitura: /dashboard_dados e /listar_ocorrencias (já existem);
     - canal de perguntas: uma rota nova no backend, com acesso somente de consulta. */
import { lerPreferencia, gravarPreferencia } from "./util.js";

const botao = document.getElementById("botao-ia");
const painel = document.getElementById("painel-ia");
const fechar = document.getElementById("ia-fechar");

function abrir(sim, { foco = true, lembrar = true } = {}) {
  painel.hidden = !sim;
  botao.setAttribute("aria-expanded", String(sim));
  document.body.dataset.ia = sim ? "aberto" : "fechado";
  if (lembrar) gravarPreferencia("assistenteAberto", sim);
  if (foco) (sim ? fechar : botao).focus();
  // o gêmeo 3D e o vídeo se redimensionam sozinhos; o evento cobre navegadores sem ResizeObserver
  window.dispatchEvent(new Event("resize"));
}

botao.addEventListener("click", () => abrir(painel.hidden));
fechar.addEventListener("click", () => abrir(false));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !painel.hidden && painel.contains(document.activeElement)) abrir(false);
});

abrir(lerPreferencia("assistenteAberto") === "true" && window.innerWidth >= 1100, { foco: false, lembrar: false });
