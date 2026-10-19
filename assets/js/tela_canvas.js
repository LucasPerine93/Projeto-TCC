import { ui } from "./conexao_ui.js";

let desenhando = false;
let xInicio = 0;
let yInicio = 0;

let areaMarcada = null;

const botaoLimpar = document.getElementById("limpar-box");
const canvas = document.getElementById("area-risco");
const ctx = canvas.getContext("2d");

function getMousePos(e) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: e.clientX - rect.left,
    y: e.clientY - rect.top,
  };
}

canvas.addEventListener("mousedown", (e) => {
  const pos = getMousePos(e);

  xInicio = pos.x;
  yInicio = pos.y;
  desenhando = true;
});

canvas.addEventListener("mousemove", (e) => {
  if (!desenhando) return;

  const pos = getMousePos(e);
  const xAtual = pos.x;
  const yAtual = pos.y;

  const width = xAtual - xInicio;
  const height = yAtual - yInicio;

  renderizarRetangulo(xInicio, yInicio, width, height);
});

function renderizarRetangulo(x1, y1, x2, y2) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  ctx.strokeStyle = "#00FF00";
  ctx.lineWidth = 2;
  ctx.fillStyle = "rgba(0, 255, 0, 0.2)";

  ctx.fillRect(x1, y1, x2, y2);
  ctx.strokeRect(x1, y1, x2, y2);
}

canvas.addEventListener("mouseup", (e) => {
  if (!desenhando) return;

  desenhando = false;

  const pos = getMousePos(e);
  const xFinal = pos.x;
  const yFinal = pos.y;

  const x1 = Math.round(Math.min(xInicio, xFinal));
  const y1 = Math.round(Math.min(yInicio, yFinal));
  const x2 = Math.round(Math.max(xInicio, xFinal));
  const y2 = Math.round(Math.max(yInicio, yFinal));

  const width = xFinal - xInicio;
  const height = yFinal - yInicio;

  if (Math.abs(width) < 5 || Math.abs(height) < 5) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }

  areaMarcada = { x1, y1, x2, y2 };

  ui.send_message("area_marcada", areaMarcada);
});

ui.on_message("box_risco", (data) => {
  if (!data || data.length !== 4) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }

  const [x1, y1, x2, y2] = data;

  const xComeco = Math.min(x1, x2);
  const yComeco = Math.min(y1, y2);
  const width = Math.abs(x2 - x1);
  const height = Math.abs(y2 - y1);

  renderizarRetangulo(xComeco, yComeco, width, height);
});

botaoLimpar.addEventListener("click", () => {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  areaMarcada = null;

  ui.send_message("limpar_box_risco", {});
});