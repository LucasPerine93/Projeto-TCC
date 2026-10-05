ui = new WebUI();
ip_unoq = window.location.hostname;

videoIframe = document.getElementById("video");
videoIframe.src = `http://${ip_unoq}:4912/embed`;

const canvas = document.getElementById("area-risco");
const ctx = canvas.getContext("2d");
const botaoLimpar = document.getElementById("limpar-box");
const botaoSenha = document.getElementById("enviar-senha");
const botaoBloquear = document.getElementById("bloquear");
const campoSenha = document.getElementById("caixa-senha");
const mensagemErro = document.getElementById("mensagem-erro");

let senhaCorreta = false;

let desenhando = false;
let comecoX = 0;
let comecoY = 0;

let area_risco = 0; // 0 é falso | 1 é verdadeiro
let area_marcada = null;

function mostrarTela() {
    document.getElementById("tela-bloqueio").style.display = "none";
    document.getElementById("video-camera").style.display = "none";

    if (senhaCorreta) {
        document.getElementById("tela-bloqueio").style.display = "none";
        document.getElementById("video-camera").style.display = "block";
    }
    else {
        document.getElementById("tela-bloqueio").style.display = "block";
        document.getElementById("video-camera").style.display = "none";
        campoSenha.focus();
    }

}

botaoSenha.addEventListener('click', () => {
    const senha = parseInt(campoSenha.value);

    ui.send_message("senha", {senha});
    campoSenha.value = "";
});

ui.on_message("senha_processada", (data) => {
    let liberacao = parseInt(data["senha_processada"]);

    if (liberacao === 0) {
        senhaCorreta = true;
    }

    if (liberacao === 1) {
        senhaCorreta = false;

    mensagemErro.innerText = "Senha incorreta, tente novamente";
    setTimeout(() => {
        mensagemErro.innerText = "";
    }, 2500);
    }

    mostrarTela();
});

botaoBloquear.addEventListener("click", () => {
    senhaCorreta = false;
    mostrarTela();
});

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

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    ctx.strokeStyle = "#00FF00";
    ctx.lineWidth = 2;
    ctx.fillStyle = "rgba(0, 255, 0, 0.2)";

    const width = Xatual - comecoX;
    const height = Yatual - comecoY;

    ctx.fillRect(comecoX, comecoY, width, height);
    ctx.strokeRect(comecoX, comecoY, width, height);
});

canvas.addEventListener("mouseup", (e) => {
    if (!desenhando) return;

    area_risco = 1;

    const pos = getMousePos(e);
    const X_final = pos.x;
    const Y_final = pos.y;

    const x1 = Math.round(Math.min(comecoX, X_final));
    const y1 = Math.round(Math.min(comecoY, Y_final));
    const x2 = Math.round(Math.max(comecoX, X_final));
    const y2 = Math.round(Math.max(comecoY, Y_final));

    const width = X_final - comecoX;
    const height = Y_final - comecoY;

    if ((Math.abs(x2 - x1) || Math.abs(y2 - y1)) < 5) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        area_marcada = null;
        return;
    }

    area_marcada = { pixels: { x1, y1, x2, y2 } };

    desenhando = false;
    console.log("Coordenadas capturadas:", area_marcada);
    ui.send_message("area-marcada", area_marcada);
    ui.send_message("risco", area_risco);
});

botaoLimpar.addEventListener("click", () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    area_marcada = null;
    area_risco = 0;
  
    ui.send_message("risco", area_risco);
});
