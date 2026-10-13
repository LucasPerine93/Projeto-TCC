import "./tela_bloqueio.js";
import "./tela_camera.js";
import "./tela_canvas.js";
import "./tela_dashboard.js";
import "./tela_galeria.js";

import { ui } from "./conexao_ui.js";
import { campoSenha } from "./tela_bloqueio.js";

export let senhaCorreta = false;
export let telaAtual = "camera"; // "camera" | "galeria" | "painel"

export const estado = {
  senhaCorreta: false,
  telaAtual: "camera"
};

export function mostrarTela() {
  document.getElementById("tela-bloqueio").style.display = "none";
  document.getElementById("video-camera").style.display = "none";
  document.getElementById("capturas-infracoes").style.display = "none";
  document.getElementById("dashboard").style.display = "none";

  if (!estado.senhaCorreta) {
    document.getElementById("tela-bloqueio").style.display = "block";
    campoSenha.focus();

    return;
  }

  if (estado.telaAtual === "painel") {
    document.getElementById("dashboard").style.display = "block";
  } else if (estado.telaAtual === "galeria") {
    document.getElementById("capturas-infracoes").style.display = "block";
  } else {
    document.getElementById("video-camera").style.display = "block";
  }
}

window.addEventListener("DOMContentLoaded", () => {
  ui.send_message("retornar_box_risco", {});
});