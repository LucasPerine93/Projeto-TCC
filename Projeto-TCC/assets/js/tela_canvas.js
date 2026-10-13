import { ui } from "./conexao_ui.js";

let desenhando = false;
let comecoX = 0;
let comecoY = 0;

let area_marcada = null;

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

  comecoX = pos.x;
  comecoY = pos.y;
  desenhando = true;
});

canvas.addEventListener("mousemove", (e) => {
  if (!desenhando) return;

  const pos = getMousePos(e);
  const Xatual = pos.x;
  const Yatual = pos.y;

  const width = Xatual - comecoX;
  const height = Yatual - comecoY;

  renderizarRetangulo(comecoX, comecoY, width, height);
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
  const X_final = pos.x;
  const Y_final = pos.y;

  const x1 = Math.round(Math.min(comecoX, X_final));
  const y1 = Math.round(Math.min(comecoY, Y_final));
  const x2 = Math.round(Math.max(comecoX, X_final));
  const y2 = Math.round(Math.max(comecoY, Y_final));

  const width = X_final - comecoX;
  const height = Y_final - comecoY;

  if (width < 5 || height < 5) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }

  area_marcada = { x1, y1, x2, y2 };

  ui.send_message("area_marcada", area_marcada);
});

ui.on_message("box_risco", (data) => {
  if (!data.length || data.length !== 4) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }

  const [x1, y1, x2, y2] = data;

  const comecoX = Math.min(x1, x2);
  const comecoY = Math.min(y1, y2);
  const width = Math.abs(x2 - x1);
  const height = Math.abs(y2 - y1);

  renderizarRetangulo(comecoX, comecoY, width, height);
});

botaoLimpar.addEventListener("click", () => {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  area_marcada = null;

  ui.send_message("limpar_box_risco", {});
});