const ui = new WebUI();
const ip_unoq = window.location.hostname;

const videoIframe = document.getElementById("video");
videoIframe.src = `http://${ip_unoq}:4912/embed`;

const canvas = document.getElementById("area-risco");
const ctx = canvas.getContext("2d");
const botaoLimpar = document.getElementById("limpar-box");
const botaoSenha = document.getElementById("enviar-senha");
const botaoBloquear = document.getElementById("bloquear");
const campoSenha = document.getElementById("caixa-senha");
const mensagemErro = document.getElementById("mensagem-erro");
const mostrarLogs = document.getElementById("mostrar-logs");
const botaoLimparLogs = document.getElementById("limpar-logs");
const botaoDashBoard = document.getElementById("botao-dashboard");
const galeria_fotos = document.getElementById("galeria-fotos");
const botaoAtualizarFotos = document.getElementById("botao-atualizar");
const botaoVoltarCamera = document.getElementById("voltar-camera");
const botaoAtualizarPainel = document.getElementById("botao-atualizar-painel");
const botaoVerGaleria = document.getElementById("ver-galeria");
const botaoVoltarPainel = document.getElementById("voltar-painel");
const imagemAmpliada = document.getElementById("foto-ampliada");
const botaoFecharImagemAmpliada = document.getElementById(
  "fechar-dados-imagem",
);

let senhaCorreta = false;

let desenhando = false;
let comecoX = 0;
let comecoY = 0;

let area_marcada = null;

let telaAtual = "camera"; // "camera" | "galeria" | "painel"

function mostrarTela() {
  document.getElementById("tela-bloqueio").style.display = "none";
  document.getElementById("video-camera").style.display = "none";
  document.getElementById("capturas-infracoes").style.display = "none";
  document.getElementById("dashboard").style.display = "none";

  if (!senhaCorreta) {
    document.getElementById("tela-bloqueio").style.display = "block";
    campoSenha.focus();

    return;
  }

  if (telaAtual === "painel") {
    document.getElementById("dashboard").style.display = "block";
  } else if (telaAtual === "galeria") {
    document.getElementById("capturas-infracoes").style.display = "block";
  } else {
    document.getElementById("video-camera").style.display = "block";
  }
}

botaoSenha.addEventListener("click", () => {
  const senha = parseInt(campoSenha.value);

  ui.send_message("senha", { senha });
  campoSenha.value = "";
});

campoSenha.addEventListener("keydown", (evento) => {
  if (evento.key === "Enter") {
    botaoSenha.click();
  }
});

ui.on_message("liberado", () => {
  senhaCorreta = true;
  carregarFotos();
  mostrarTela();
});

ui.on_message("rejeitado", () => {
  senhaCorreta = false;
  mostrarTela();

  mensagemErro.innerText = "Senha incorreta, tente novamente";
  setTimeout(() => {
    mensagemErro.innerText = "";
  }, 2500);
});

botaoBloquear.addEventListener("click", () => {
  senhaCorreta = false;
  telaAtual = "camera";
  mostrarTela();
});

ui.on_message("log_deteccao", (log) => {
  const novoLog = document.createElement("span");

  novoLog.classList.add("mostrar-logs");
  novoLog.innerText = log + "\n";
  mostrarLogs.appendChild(novoLog);
});

botaoLimparLogs.addEventListener("click", () => {
  mostrarLogs.innerHTML = "";
});

botaoDashBoard.addEventListener("click", () => {
  telaAtual = "painel";
  carregarDashboard();
  mostrarTela();
});

botaoVoltarPainel.addEventListener("click", () => {
  telaAtual = "camera";
  mostrarTela();
});

botaoVerGaleria.addEventListener("click", () => {
  telaAtual = "galeria";
  carregarFotos();
  mostrarTela();
});

botaoAtualizarPainel.addEventListener("click", carregarDashboard);

async function carregarFotos() {
  let dadosFoto;
  try {
    const resposta_ocorrencias = await fetch("/listar_ocorrencias");
    if (!resposta_ocorrencias.ok) {
      throw new Error(
        `Falha ao carregar ocorrências (HTTP ${resposta_ocorrencias.status})`,
      );
    }
    dadosFoto = await resposta_ocorrencias.json();
  } catch (erro) {
    console.error("Erro ao carregar galeria:", erro);
    // Mantém a mensagem de "galeria vazia" visível em caso de falha.
    galeria_fotos.innerHTML = "";
    return;
  }

  galeria_fotos.innerHTML = "";

  dadosFoto.forEach((dado) => {
    // Cartão moderno (mesmo padrão visual do painel analítico).
    const card = document.createElement("figure");
    card.className = "foto-card";

    // Selo com ícone SVG no canto do cartão.
    const badge = document.createElement("span");
    badge.className = "foto-card-badge";
    badge.innerHTML =
      '<svg class="ic" aria-hidden="true"><use href="#ic-camera" /></svg>';

    const foto = document.createElement("img");
    foto.src = `/foto/${dado.caminho_foto}`;
    foto.alt = `Evidência: ${dado.tipo_infracao}`;
    foto.loading = "lazy";

    // Rodapé com o tipo de infração e a data/hora do registro.
    const info = document.createElement("figcaption");
    info.className = "foto-card-info";

    const tipo = document.createElement("span");
    tipo.className = "foto-card-tipo";
    tipo.innerText = dado.tipo_infracao;

    const data = document.createElement("span");
    data.className = "foto-card-data";
    data.innerText = `#${dado.id} · ${new Date(dado.timestamp).toLocaleString(
      "pt-BR",
    )}`;

    info.appendChild(tipo);
    info.appendChild(data);

    card.appendChild(badge);
    card.appendChild(foto);
    card.appendChild(info);

    // Abre o modal de detalhes ao clicar em qualquer parte do cartão.
    card.addEventListener("click", () => {
      mostrarDetalhesFoto(dado);
    });

    galeria_fotos.appendChild(card);
  });
}

botaoAtualizarFotos.addEventListener("click", carregarFotos);

// Guarda a instância do gráfico para poder destruí-la antes de recriar.
let graficoConformidade = null;

async function carregarDashboard() {
  let dados;
  try {
    const resposta = await fetch("/dashboard_dados");
    if (!resposta.ok) {
      throw new Error(`Falha ao carregar dados (HTTP ${resposta.status})`);
    }
    dados = await resposta.json();
  } catch (erro) {
    console.error("Erro ao carregar dashboard:", erro);
    document.getElementById("kpi-total").innerText = "--";
    document.getElementById("kpi-tipos").innerText = "--";
    return;
  }

  // --- KPIs ---
  document.getElementById("kpi-total").innerText = dados.total_observacoes;
  document.getElementById("kpi-tipos").innerText = Object.keys(
    dados.resumo_conformidade,
  ).length;

  // Infração mais comum (maior contagem em resumo_conformidade).
  const tiposInfra = Object.keys(dados.resumo_conformidade);
  if (tiposInfra.length > 0) {
    const maisComum = tiposInfra.reduce((a, b) =>
      dados.resumo_conformidade[a] >= dados.resumo_conformidade[b] ? a : b,
    );
    document.getElementById("kpi-comum").innerText = maisComum;
    document.getElementById("kpi-comum").title =
      `${dados.resumo_conformidade[maisComum]} ocorrências`;
  } else {
    document.getElementById("kpi-comum").innerText = "--";
  }

  // Última ocorrência registrada (eventos_recentes vem ordenado por id DESC).
  const ultima = dados.eventos_recentes?.[0];
  document.getElementById("kpi-ultima").innerText = ultima?.timestamp
    ? new Date(ultima.timestamp).toLocaleString("pt-BR")
    : "--";

  // --- Gráfico de distribuição das infrações ---
  const rotulos = Object.keys(dados.resumo_conformidade);
  const valores = Object.values(dados.resumo_conformidade);

  if (graficoConformidade) {
    graficoConformidade.destroy();
  }

  graficoConformidade = new Chart(
    document.getElementById("grafico-conformidade"),
    {
      type: "doughnut",
      data: {
        labels: rotulos,
        datasets: [
          {
            data: valores,
            backgroundColor: [
              "#38bdf8",
              "#f87171",
              "#fbbf24",
              "#4ade80",
              "#a78bfa",
              "#fb923c",
            ],
            borderColor: "rgba(13, 23, 42, 0.9)",
            borderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: {
          legend: {
            position: "bottom",
            labels: { color: "#e2e8f0" },
          },
        },
      },
    },
  );

  // --- Tabela de eventos recentes ---
  const corpoTabela = document.getElementById("tabela-eventos-corpo");
  corpoTabela.innerHTML = "";

  dados.eventos_recentes.forEach((evento) => {
    const linha = document.createElement("tr");

    const dataFormatada = new Date(evento.timestamp).toLocaleString("pt-BR");

    linha.innerHTML = `
      <td>${dataFormatada}</td>
      <td>${evento.tipo_infracao}</td>
      <td>${evento.posicao_x?.toFixed(1) ?? "--"}</td>
      <td>${evento.posicao_y?.toFixed(1) ?? "--"}</td>
      <td>${evento.conf_pessoa?.toFixed(2) ?? "--"}</td>
    `;

    corpoTabela.appendChild(linha);
  });
}

// Aplica o valor textual e preenche a barra de progresso com cor por faixa.
function aplicarBarraConfianca(idValor, idBarra, valor) {
  const rotulo = document.getElementById(idValor);
  const barra = document.getElementById(idBarra);
  if (!rotulo || !barra) return;

  if (valor === null || valor === undefined || isNaN(valor)) {
    rotulo.innerText = "--";
    barra.style.width = "0%";
    barra.classList.remove("conf-alta", "conf-media", "conf-baixa");
    return;
  }

  const porcentagem = Math.round(valor * 100);
  rotulo.innerText = `${porcentagem}%`;

  barra.style.width = `${porcentagem}%`;
  barra.classList.remove("conf-alta", "conf-media", "conf-baixa");
  if (porcentagem >= 75) {
    barra.classList.add("conf-alta");
  } else if (porcentagem >= 50) {
    barra.classList.add("conf-media");
  } else {
    barra.classList.add("conf-baixa");
  }
}

function mostrarDetalhesFoto(dado) {
  imagemAmpliada.src = `/foto/${dado.caminho_foto}`;

  document.getElementById("data-infracao").innerText = new Date(
    dado.timestamp,
  ).toLocaleString("pt-BR");
  document.getElementById("tipo-infracao").innerText = dado.tipo_infracao;

  document.getElementById("posicaox-infracao").innerText =
    dado.posicao_x?.toFixed(1) ?? "--";
  document.getElementById("posicaoy-infracao").innerText =
    dado.posicao_y?.toFixed(1) ?? "--";

  aplicarBarraConfianca(
    "confiancap-infracao",
    "barra-conf-pessoa",
    dado.conf_pessoa,
  );
  aplicarBarraConfianca(
    "confiancacp-infracao",
    "barra-conf-capacete",
    dado.conf_capacete,
  );
  aplicarBarraConfianca(
    "confiancacl-infracao",
    "barra-conf-colete",
    dado.conf_colete,
  );

  document.getElementById("mostrar-dados-imagem").style.display = "block";
}

// Fecha o modal de detalhes ao clicar no fundo escurecido (overlay).
document.getElementById("mostrar-dados-imagem").addEventListener("click", (e) => {
  if (e.target.id === "mostrar-dados-imagem") {
    document.getElementById("mostrar-dados-imagem").style.display = "none";
  }
});

botaoFecharImagemAmpliada.addEventListener("click", () => {
  document.getElementById("mostrar-dados-imagem").style.display = "none";
});

botaoVoltarCamera.addEventListener("click", () => {
  telaAtual = "camera";
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

window.addEventListener("DOMContentLoaded", () => {
  ui.send_message("retornar_box_risco", {});
});

botaoLimpar.addEventListener("click", () => {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  area_marcada = null;

  ui.send_message("limpar_box_risco", {});
});