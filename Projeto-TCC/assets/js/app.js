/* =========================================================================
   app.js — Ponto de entrada do frontend (monta as telas e liga os eventos)
   -------------------------------------------------------------------------
   Controla:
   - imports de todos os módulos (a ORDEM é significativa: tema.js primeiro,
     depois a UI, depois as telas registradas por último);
   - clique nas abas (#abas [data-tela]) -> irPara(...);
   - clique em "Sair" (#botao-sair) -> tela_bloqueio;
   - fluxo de acesso (iniciarAcesso): ativa Ao vivo, Ocorrências e Painel e
     decide a tela inicial (#/hash ou "ao-vivo").
   ========================================================================= */
// ===== 1. Importações e ordem de carga =====
import "./tema.js";
import { ui } from "./conexao_ui.js";
import { estado, irPara, telaDoHash } from "./nucleo.js";
import { iniciarAcesso, sair } from "./tela_bloqueio.js";
import { iniciarAoVivo, pararAoVivo } from "./tela_ao_vivo.js";
import { iniciarOcorrencias, pararOcorrencias } from "./tela_ocorrencias.js";
import "./tela_painel.js";
import { pararGemeo } from "./tela_gemeo.js";
import "./assistente.js";

// ===== 2. Abas, botão de sair e fluxo de acesso =====
document.querySelectorAll("#abas [data-tela]").forEach((b) =>
  b.addEventListener("click", () => irPara(b.dataset.tela)));
document.getElementById("botao-sair").addEventListener("click", sair);

iniciarAcesso({
  entrou: () => {
    ui.send_message("retornar_box_risco", {});
    iniciarAoVivo();
    iniciarOcorrencias();
    irPara(telaDoHash() || "ao-vivo", { historico: false });
  },
  saiu: () => { pararAoVivo(); pararOcorrencias(); pararGemeo(); },
});
