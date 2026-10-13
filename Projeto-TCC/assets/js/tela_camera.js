import { mostrarTela, estado } from "./app.js";
import { carregarDashboard } from "./tela_dashboard.js";
import { carregarFotos } from "./tela_galeria.js";
import { ui } from "./conexao_ui.js";

const ip_unoq = window.location.hostname;

const videoIframe = document.getElementById("video");
const cameraPlaceholder = document.getElementById("camera-placeholder");

// Só carrega o stream quando o UNO Q responder; caso contrário, mantém o
// placeholder elegante em vez do fundo cinza/erro padrão do navegador.
async function carregarTransmissao() {
  const endereco = `http://${ip_unoq}:4912/embed`;
  const controle = new AbortController();
  const tempoLimite = setTimeout(() => controle.abort(), 2500);

  try {
    await fetch(endereco, { mode: "no-cors", signal: controle.signal });
    cameraPlaceholder.hidden = true;
    videoIframe.src = endereco;
  } catch (erro) {
    // Sem transmissão no momento: placeholder permanece visível.
  } finally {
    clearTimeout(tempoLimite);
  }
}

carregarTransmissao();

const botaoLimparLogs = document.getElementById("limpar-logs");
const botaoBloquear = document.getElementById("bloquear");
const botaoDashBoard = document.getElementById("botao-dashboard");
const botaoVerGaleria = document.getElementById("ver-galeria");
const mostrarLogs = document.getElementById("mostrar-logs");
const botaoAlertaSonoro = document.getElementById("toggle-alerta-sonoro");
const textoAlertaSonoro = document.getElementById("texto-alerta-sonoro");
const videoContainer = document.querySelector(".video-container");

let alertaSonoroAtivo = localStorage.getItem("alertaSonoroAtivo") === "true";
let contextoAudio = null;
let temporizadorAlertaVisual = null;

function atualizarBotaoAlertaSonoro() {
  textoAlertaSonoro.innerText = `Alerta sonoro: ${alertaSonoroAtivo ? "Ativado" : "Desativado"}`;
  botaoAlertaSonoro.setAttribute("aria-pressed", String(alertaSonoroAtivo));
  botaoAlertaSonoro.classList.toggle("alerta-sonoro-ativo", alertaSonoroAtivo);
}

function emitirBipe() {
  const AudioContextNativo = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextNativo) return;
  contextoAudio ??= new AudioContextNativo();
  if (contextoAudio.state === "suspended") contextoAudio.resume();

  const oscilador = contextoAudio.createOscillator();
  const ganho = contextoAudio.createGain();
  oscilador.type = "sine";
  oscilador.frequency.value = 880;
  ganho.gain.setValueAtTime(0.0001, contextoAudio.currentTime);
  ganho.gain.exponentialRampToValueAtTime(0.12, contextoAudio.currentTime + 0.01);
  ganho.gain.exponentialRampToValueAtTime(0.0001, contextoAudio.currentTime + 0.16);
  oscilador.connect(ganho).connect(contextoAudio.destination);
  oscilador.start();
  oscilador.stop(contextoAudio.currentTime + 0.17);
}

function sinalizarInfracao() {
  videoContainer.classList.remove("alerta-infracao-visual");
  void videoContainer.offsetWidth;
  videoContainer.classList.add("alerta-infracao-visual");
  window.clearTimeout(temporizadorAlertaVisual);
  temporizadorAlertaVisual = window.setTimeout(() => {
    videoContainer.classList.remove("alerta-infracao-visual");
  }, 1200);
  if (alertaSonoroAtivo) emitirBipe();
}

function ehLogDeInfracao(log) {
  return /\[ALERTA\]|sem capacete|sem colete|área de risco/i.test(String(log));
}

botaoAlertaSonoro.addEventListener("click", () => {
  alertaSonoroAtivo = !alertaSonoroAtivo;
  localStorage.setItem("alertaSonoroAtivo", String(alertaSonoroAtivo));
  if (alertaSonoroAtivo) emitirBipe();
  atualizarBotaoAlertaSonoro();
});
atualizarBotaoAlertaSonoro();

ui.on_message("log_deteccao", (log) => {
  const novoLog = document.createElement("span");

  novoLog.classList.add("mostrar-logs");
  novoLog.innerText = log + "\n";
  mostrarLogs.appendChild(novoLog);
  mostrarLogs.scrollTop = mostrarLogs.scrollHeight;

  if (ehLogDeInfracao(log)) sinalizarInfracao();
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