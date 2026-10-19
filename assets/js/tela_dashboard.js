import { navegarPara } from "./app.js";
import { formatarDataHora } from "./utils/formatarDataHora.js";

// Guarda a instância do gráfico para poder destruí-la antes de recriar.
let graficoConformidade = null;

const botaoAtualizarPainel = document.getElementById("botao-atualizar-painel");
const botaoVoltarPainel = document.getElementById("voltar-painel");

export async function carregarDashboard() {
  const resposta = await fetch("/dashboard_dados");

  if (!resposta.ok) {
    console.error("Erro ao carregar dashboard:", `(HTTP ${resposta.status})`);
    document.getElementById("kpi-total").innerText = "--";
    document.getElementById("kpi-tipos").innerText = "--";
    return;
  }
  let dados = await resposta.json();

  atualizarKPIs(dados);
  renderizarGraficos(dados);
  renderizarTabela(dados);
}

function atualizarKPIs(dados) {
  document.getElementById("kpi-total").innerText = dados.total_observacoes;
  document.getElementById("kpi-tipos").innerText = Object.keys(dados.resumo_conformidade,).length;

  const tiposInfra = Object.keys(dados.resumo_conformidade);
    if (tiposInfra.length > 0) {
        const maisComum = tiposInfra.reduce((a, b) => dados.resumo_conformidade[a] >= dados.resumo_conformidade[b] ? a : b);

        document.getElementById("kpi-comum").innerText = maisComum;
        document.getElementById("kpi-comum").title = `${dados.resumo_conformidade[maisComum]} ocorrências`;

  } else {
    document.getElementById("kpi-comum").innerText = "--";
  }

  // Última ocorrência registrada (eventos_recentes vem ordenado por id DESC).
  const ultima = dados.eventos_recentes?.[0];
  document.getElementById("kpi-ultima").innerText = ultima?.timestamp ? formatarDataHora(ultima.timestamp): "--";
}

function renderizarGraficos(dados) {
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
}

function renderizarTabela(dados) {
  const corpoTabela = document.getElementById("tabela-eventos-corpo");
  corpoTabela.innerHTML = "";

  dados.eventos_recentes.forEach((evento) => {
    const linha = document.createElement("tr");

    const dataFormatada = formatarDataHora(evento.timestamp);

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

botaoVoltarPainel.addEventListener("click", () => navegarPara("camera"));

botaoAtualizarPainel.addEventListener("click", carregarDashboard);