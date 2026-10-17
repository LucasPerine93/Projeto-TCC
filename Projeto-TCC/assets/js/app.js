import "./tema.js";
import { ui } from "./conexao_ui.js";
import { estado, irPara, telaDoHash } from "./nucleo.js";
import { iniciarAcesso, sair } from "./tela_bloqueio.js";
import { iniciarAoVivo, pararAoVivo } from "./tela_ao_vivo.js";
import { iniciarOcorrencias, pararOcorrencias } from "./tela_ocorrencias.js";
import "./tela_painel.js";

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
  saiu: () => { pararAoVivo(); pararOcorrencias(); },
});
