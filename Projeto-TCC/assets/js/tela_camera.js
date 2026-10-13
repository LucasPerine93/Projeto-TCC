import { mostrarTela, estado } from "./app.js";
import { carregarDashboard } from "./tela_dashboard.js";
import { carregarFotos } from "./tela_galeria.js";
import { ui } from "./conexao_ui.js";

const ip_unoq = window.location.hostname;

const videoIframe = document.getElementById("video");
videoIframe.src = `http://${ip_unoq}:4912/embed`;

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

botaoLimparLogs.addEventListener("click", () => {
  mostrarLogs.innerHTML = "";
});

botaoBloquear.addEventListener("click", () => {
  estado.senhaCorreta = false;
  estado.telaAtual = "camera";
  mostrarTela();
});

botaoDashBoard.addEventListener("click", () => {
  estado.telaAtual = "painel";
  carregarDashboard();
  mostrarTela();
});

botaoVerGaleria.addEventListener("click", () => {
  estado.telaAtual = "galeria";
  carregarFotos();
  mostrarTela();
});