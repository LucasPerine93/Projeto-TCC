/* Tela "Ao vivo": vídeo, estado do sistema, eventos e área de risco. */
import { ui } from "./conexao_ui.js";
import { el, icone, hora, lerPreferencia, gravarPreferencia } from "./util.js";
import { registrarTela, definirChip, avisar, irPara } from "./nucleo.js";

const quadro = document.getElementById("quadro-video");
const iframe = document.getElementById("video");
const placeholder = document.getElementById("camera-placeholder");
const mensagemCamera = document.getElementById("camera-msg");
const canvas = document.getElementById("area-risco");
const ctx = canvas.getContext("2d");
const botaoDefinir = document.getElementById("botao-definir-area");
const botaoRemover = document.getElementById("botao-remover-area");
const dica = document.getElementById("dica-area");
const botaoSom = document.getElementById("botao-som");
const botaoLimpar = document.getElementById("botao-limpar-logs");
const listaLogs = document.getElementById("lista-logs");
const logsVazio = document.getElementById("logs-vazio");

const DICA_PADRAO = dica.textContent.trim();
const MAX_LOGS = 300;

/* ---------- Estado do socket ---------- */
function marcarConexao(conectado) {
  definirChip("chip-conexao", conectado ? "ok" : "critico", conectado ? "Conectado" : "Sem conexão");
}
if (typeof ui.on_connect === "function") ui.on_connect(() => marcarConexao(true));
if (typeof ui.on_disconnect === "function") ui.on_disconnect(() => marcarConexao(false));

/* ---------- Câmera ---------- */
let temporizadorCamera = null;
let cameraNoAr = false;

async function verificarCamera() {
  const endereco = `http://${window.location.hostname}:4912/embed`;
  const controle = new AbortController();
  const limite = setTimeout(() => controle.abort(), 2500);
  try {
    await fetch(endereco, { mode: "no-cors", signal: controle.signal });
    if (!cameraNoAr) {
      iframe.src = endereco;
      placeholder.hidden = true;
      cameraNoAr = true;
    }
    definirChip("chip-camera", "ok", "Câmera no ar");
  } catch {
    cameraNoAr = false;
    placeholder.hidden = false;
    mensagemCamera.textContent = "Sem sinal da câmera. Verifique a alimentação e a rede da placa.";
    definirChip("chip-camera", "critico", "Câmera sem sinal");
  } finally {
    clearTimeout(limite);
  }
}

export function iniciarAoVivo() {
  pararAoVivo();
  verificarCamera();
  temporizadorCamera = window.setInterval(verificarCamera, 8000);
  ui.send_message("retornar_box_risco", {});
}
export function pararAoVivo() {
  window.clearInterval(temporizadorCamera);
  temporizadorCamera = null;
  cameraNoAr = false;
  iframe.removeAttribute("src");
  cancelarDefinicao();
}

/* ---------- Eventos (logs) ---------- */
let somAtivo = lerPreferencia("alertaSonoroAtivo") === "true";
let contextoAudio = null;
let temporizadorAlerta = null;

function atualizarBotaoSom() {
  botaoSom.setAttribute("aria-pressed", String(somAtivo));
  botaoSom.querySelector("span").textContent = `Alerta sonoro: ${somAtivo ? "ligado" : "desligado"}`;
  botaoSom.querySelector("use").setAttribute("href", `icones.svg#${somAtivo ? "som" : "mudo"}`);
}

function bipe() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return;
  contextoAudio ??= new AC();
  if (contextoAudio.state === "suspended") contextoAudio.resume();
  const osc = contextoAudio.createOscillator();
  const ganho = contextoAudio.createGain();
  const t = contextoAudio.currentTime;
  osc.type = "sine";
  osc.frequency.value = 880;
  ganho.gain.setValueAtTime(0.0001, t);
  ganho.gain.exponentialRampToValueAtTime(0.12, t + 0.01);
  ganho.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
  osc.connect(ganho).connect(contextoAudio.destination);
  osc.start();
  osc.stop(t + 0.17);
}

function sinalizar() {
  quadro.classList.remove("alerta");
  void quadro.offsetWidth;
  quadro.classList.add("alerta");
  window.clearTimeout(temporizadorAlerta);
  temporizadorAlerta = window.setTimeout(() => quadro.classList.remove("alerta"), 1400);
  if (somAtivo) bipe();
}

botaoSom.addEventListener("click", () => {
  somAtivo = !somAtivo;
  gravarPreferencia("alertaSonoroAtivo", somAtivo);
  if (somAtivo) bipe();
  atualizarBotaoSom();
});
atualizarBotaoSom();

/** "[ALERTA]: texto" -> { tag, texto, classe, icone } */
function classificar(bruto) {
  const m = String(bruto).match(/^\s*\[([^\]]+)\]\s*:?\s*(.*)$/s);
  const tag = m ? m[1].toUpperCase() : "";
  const texto = (m ? m[2] : String(bruto)).trim();
  if (/ALERTA|ERRO|FALHA/.test(tag)) return { texto, classe: "log-critico", icone: "x", infracao: /ALERTA/.test(tag) };
  if (/AVISO|ATEN/.test(tag)) return { texto, classe: "log-aviso", icone: "aviso", infracao: false };
  if (/OK|SUCESSO|SALV/.test(tag) || /cena salva/i.test(texto)) return { texto, classe: "log-ok", icone: "ok", infracao: false };
  return {
    texto, classe: "log-info", icone: "alerta",
    infracao: /sem capacete|sem colete|área de risco|area de risco/i.test(texto),
  };
}

ui.on_message("log_deteccao", (bruto) => {
  const info = classificar(bruto);
  const agora = new Date();
  const preso = listaLogs.scrollTop + listaLogs.clientHeight >= listaLogs.scrollHeight - 24;

  listaLogs.append(el("li", { class: `log ${info.classe}` },
    el("time", { datetime: agora.toISOString() }, hora(agora)),
    icone(info.icone),
    el("span", {}, info.texto)));
  while (listaLogs.children.length > MAX_LOGS) listaLogs.firstElementChild.remove();
  logsVazio.hidden = true;
  if (preso) listaLogs.scrollTop = listaLogs.scrollHeight;

  if (info.infracao) sinalizar();
  if (/cena salva/i.test(info.texto)) {
    document.dispatchEvent(new CustomEvent("nova-ocorrencia"));
    avisar("Nova ocorrência registrada.", {
      tipo: "aviso", acao: { rotulo: "Revisar", aoClicar: () => irPara("ocorrencias") },
    });
  }
});

botaoLimpar.addEventListener("click", () => {
  listaLogs.replaceChildren();
  logsVazio.hidden = false;
});

/* ---------- Área de risco ---------- */
let definindo = false;
let inicio = null;
let areaAtual = null; // [x1,y1,x2,y2] em pixels do quadro 720x480

function posicao(e) {
  const r = canvas.getBoundingClientRect();
  const x = ((e.clientX - r.left) * canvas.width) / r.width;
  const y = ((e.clientY - r.top) * canvas.height) / r.height;
  return { x: Math.max(0, Math.min(canvas.width, x)), y: Math.max(0, Math.min(canvas.height, y)) };
}

function retangulo(x1, y1, x2, y2) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const x = Math.min(x1, x2), y = Math.min(y1, y2), w = Math.abs(x2 - x1), h = Math.abs(y2 - y1);
  ctx.fillStyle = "rgba(239, 68, 68, 0.22)";
  ctx.strokeStyle = "#ef4444";
  ctx.lineWidth = 3;
  ctx.setLineDash([10, 6]);
  ctx.fillRect(x, y, w, h);
  ctx.strokeRect(x, y, w, h);
  ctx.setLineDash([]);
}

function mostrarArea(area) {
  areaAtual = Array.isArray(area) && area.length === 4 ? area.map(Number) : null;
  if (areaAtual) retangulo(...areaAtual);
  else ctx.clearRect(0, 0, canvas.width, canvas.height);
  botaoRemover.disabled = !areaAtual;
  definirChip("chip-area", areaAtual ? "ok" : "neutro", areaAtual ? "Área de risco ativa" : "Sem área de risco");
  botaoDefinir.querySelector("span").textContent = areaAtual ? "Redefinir área de risco" : "Definir área de risco";
}

function cancelarDefinicao() {
  definindo = false;
  inicio = null;
  quadro.classList.remove("desenhando");
  botaoDefinir.setAttribute("aria-pressed", "false");
  dica.textContent = DICA_PADRAO;
  mostrarArea(areaAtual);
}

botaoDefinir.addEventListener("click", () => {
  if (definindo) { cancelarDefinicao(); return; }
  definindo = true;
  quadro.classList.add("desenhando");
  botaoDefinir.setAttribute("aria-pressed", "true");
  dica.textContent = "Arraste sobre o vídeo para marcar a área. Esc cancela.";
  ctx.clearRect(0, 0, canvas.width, canvas.height);
});

canvas.addEventListener("pointerdown", (e) => {
  if (!definindo) return;
  e.preventDefault();
  canvas.setPointerCapture(e.pointerId);
  inicio = posicao(e);
});
canvas.addEventListener("pointermove", (e) => {
  if (!definindo || !inicio) return;
  const p = posicao(e);
  retangulo(inicio.x, inicio.y, p.x, p.y);
});
canvas.addEventListener("pointerup", (e) => {
  if (!definindo || !inicio) return;
  const p = posicao(e);
  const area = {
    x1: Math.round(Math.min(inicio.x, p.x)), y1: Math.round(Math.min(inicio.y, p.y)),
    x2: Math.round(Math.max(inicio.x, p.x)), y2: Math.round(Math.max(inicio.y, p.y)),
  };
  inicio = null;
  if (area.x2 - area.x1 < 10 || area.y2 - area.y1 < 10) {
    dica.textContent = "Área muito pequena. Arraste um retângulo maior.";
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }
  ui.send_message("area_marcada", area);
  mostrarArea([area.x1, area.y1, area.x2, area.y2]);
  cancelarDefinicao();
  avisar("Área de risco definida.", { tipo: "ok", duracao: 3500 });
});
canvas.addEventListener("pointercancel", () => { inicio = null; mostrarArea(areaAtual); });

document.addEventListener("keydown", (e) => { if (e.key === "Escape" && definindo) cancelarDefinicao(); });

botaoRemover.addEventListener("click", () => {
  const anterior = areaAtual;
  if (!anterior) return;
  ui.send_message("limpar_box_risco", {});
  mostrarArea(null);
  avisar("Área de risco removida.", {
    acao: {
      rotulo: "Desfazer",
      aoClicar: () => {
        ui.send_message("area_marcada", { x1: anterior[0], y1: anterior[1], x2: anterior[2], y2: anterior[3] });
        mostrarArea(anterior);
      },
    },
  });
});

ui.on_message("box_risco", (dados) => {
  if (definindo) return;
  mostrarArea(dados);
});

registrarTela("ao-vivo", {});
