import "./tela_bloqueio.js";
import "./tela_camera.js";
import "./tela_canvas.js";
import "./tela_dashboard.js";
import "./tela_galeria.js";

import { ui } from "./conexao_ui.js";
import { campoSenha } from "./tela_bloqueio.js";
import { carregarDashboard } from "./tela_dashboard.js";
import { carregarFotos } from "./tela_galeria.js";

export function navegarPara(tela) {
  document.getElementById("tela-bloqueio").style.display = "none";
  document.getElementById("video-camera").style.display = "none";
  document.getElementById("capturas-infracoes").style.display = "none";
  document.getElementById("dashboard").style.display = "none";

  if (tela === "telaBloqueio") {
    document.getElementById("tela-bloqueio").style.display = "block";
    campoSenha.focus();

    return;
  }
  else if (tela === "painel") {
    carregarDashboard();
    document.getElementById("dashboard").style.display = "block";
  }
  else if (tela === "galeria") {
    carregarFotos();
    document.getElementById("capturas-infracoes").style.display = "block";

  } else if (tela === "camera") {
    document.getElementById("video-camera").style.display = "block";

  } else {
    console.error("Tela não encontrada");
    return;

  }
}

window.addEventListener("DOMContentLoaded", () => {
  ui.send_message("retornar_box_risco", {});
});
