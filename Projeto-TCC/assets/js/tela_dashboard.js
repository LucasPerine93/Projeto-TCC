import { mostrarTela, estado } from "./app.js";

// Guarda a instância do gráfico para poder destruí-la antes de recriar.
let graficoConformidade = null;

const botaoAtualizarPainel = document.getElementById("botao-atualizar-painel");
const botaoVoltarPainel = document.getElementById("voltar-painel");


export async function carregarDashboard() {
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
  document.getElementById("kpi-tipos").innerText = Object.keys(dados.resumo_conformidade,).length;

  // Infração mais comum (maior contagem em resumo_conformidade).
  const tiposInfra = Object.keys(dados.resumo_conformidade);
    if (tiposInfra.length > 0) {
        const maisComum = tiposInfra.reduce((a, b) =>
            dados.resumo_conformidade[a] >= dados.resumo_conformidade[b] ? a : b,
        );

        document.getElementById("kpi-comum").innerText = maisComum;
        document.getElementById("kpi-comum").title = `${dados.resumo_conformidade[maisComum]} ocorrências`;

  } else {
    document.getElementById("kpi-comum").innerText = "--";
  }

  // Última ocorrência registrada (eventos_recentes vem ordenado por id DESC).
  const ultima = dados.eventos_recentes?.[0];
  document.getElementById("kpi-ultima").innerText = ultima?.timestamp
    ? new Date(ultima.timestamp).toLocaleString("pt-BR"): "--";

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
export function aplicarBarraConfianca(idValor, idBarra, valor) {
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

botaoVoltarPainel.addEventListener("click", () => {
  estado.telaAtual = "camera";
  mostrarTela();
});

botaoAtualizarPainel.addEventListener("click", carregarDashboard);