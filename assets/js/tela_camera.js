import { navegarPara } from "./app.js";
import { ui } from "./conexao_ui.js";

const ipUnoq = window.location.hostname;

const videoIframe = document.getElementById("video");
videoIframe.src = `http://${ipUnoq}:4912/embed`;

const botaoLimparLogs = document.getElementById("limpar-logs");
const botaoBloquear = document.getElementById("bloquear");
const botaoDashBoard = document.getElementById("botao-dashboard");
const botaoVerGaleria = document.getElementById("ver-galeria");
const mostrarLogs = document.getElementById("mostrar-logs");

ui.on_message("log_deteccao", (log) => {
  const novoLog = document.createElement("span");

  novoLog.classList.add("mostrar-logs");
  novoLog.innerText = log + "\n";
  mostrarLogs.appendChild(novoLog);
});

botaoLimparLogs.addEventListener("click", () => mostrarLogs.innerHTML = "");

botaoBloquear.addEventListener("click", () => navegarPara("telaBloqueio"));

botaoDashBoard.addEventListener("click", () => navegarPara("painel"));

botaoVerGaleria.addEventListener("click", () => navegarPara("galeria"));