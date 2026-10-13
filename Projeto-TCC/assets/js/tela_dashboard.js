import { mostrarTela, estado } from "./app.js";

// Guarda a instância do gráfico para poder destruí-la antes de recriar.
let graficoConformidade = null;
let ocorrenciasAtuais = [];

const botaoAtualizarPainel = document.getElementById("botao-atualizar-painel");
const botaoVoltarPainel = document.getElementById("voltar-painel");
const botaoExportarCsv = document.getElementById("botao-exportar-csv");
const avisoExportacaoCsv = document.getElementById("aviso-exportacao-csv");


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

  ocorrenciasAtuais = Array.isArray(dados.eventos_recentes) ? dados.eventos_recentes : [];

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
    graficoConformidade = null;
  }

  const avisoVazio = document.getElementById("grafico-vazio");
  const canvasGrafico = document.getElementById("grafico-conformidade");

  // Estado vazio: sem dados, exibe mensagem discreta em vez do donut vazio.
  if (rotulos.length === 0) {
    canvasGrafico.hidden = true;
    avisoVazio.hidden = false;
  } else {
    canvasGrafico.hidden = false;
    avisoVazio.hidden = true;

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

  // --- Tabela de eventos recentes ---
  const corpoTabela = document.getElementById("tabela-eventos-corpo");
  corpoTabela.innerHTML = "";

  ocorrenciasAtuais.forEach((evento) => {
    const linha = document.createElement("tr");
    linha.className = "linha-evento-clicavel";
    linha.tabIndex = 0;
    linha.setAttribute("role", "button");
    linha.setAttribute("aria-label", `Abrir detalhes da ocorrência ${evento.id}`);

    const dataFormatada = new Date(evento.timestamp).toLocaleString("pt-BR");

    linha.innerHTML = `
      <td>${dataFormatada}</td>
      <td>${evento.tipo_infracao}</td>
      <td>${evento.posicao_x?.toFixed(1) ?? "--"}</td>
      <td>${evento.posicao_y?.toFixed(1) ?? "--"}</td>
      <td>${evento.conf_pessoa?.toFixed(2) ?? "--"}</td>
    `;

    const abrirDetalhes = () => {
      // Importação dinâmica evita acoplamento circular entre Dashboard e Galeria.
      import("./tela_galeria.js").then(({ abrirDetalhesOcorrencia }) => {
        abrirDetalhesOcorrencia(evento);
      });
    };
    linha.addEventListener("click", abrirDetalhes);
    linha.addEventListener("keydown", (tecla) => {
      if (tecla.key === "Enter" || tecla.key === " ") {
        tecla.preventDefault();
        abrirDetalhes();
      }
    });

    corpoTabela.appendChild(linha);
  });
}

function escaparCsv(valor) {
  const texto = valor === null || valor === undefined ? "" : String(valor);
  return `"${texto.replaceAll('"', '""')}"`;
}

function formatarPercentualCsv(valor) {
  const numero = Number(valor);
  return Number.isFinite(numero) ? (numero * 100).toFixed(2) : "";
}

function mostrarAvisoExportacao(mensagem) {
  avisoExportacaoCsv.innerText = mensagem;
  avisoExportacaoCsv.hidden = false;
  window.clearTimeout(mostrarAvisoExportacao.tempo);
  mostrarAvisoExportacao.tempo = window.setTimeout(() => {
    avisoExportacaoCsv.hidden = true;
  }, 3500);
}

function exportarCsv() {
  if (ocorrenciasAtuais.length === 0) {
    mostrarAvisoExportacao("Não há ocorrências disponíveis para exportação.");
    return;
  }

  const cabecalho = [
    "ID", "Data/Hora", "Tipo de Infração", "Posição X", "Posição Y",
    "Confiança Pessoa (%)", "Confiança Capacete (%)", "Confiança Colete (%)", "Arquivo da Foto",
  ];
  const linhas = ocorrenciasAtuais.map((evento) => [
    evento.id,
    evento.timestamp ? new Date(evento.timestamp).toLocaleString("pt-BR") : "",
    evento.tipo_infracao,
    evento.posicao_x ?? "",
    evento.posicao_y ?? "",
    formatarPercentualCsv(evento.conf_pessoa),
    formatarPercentualCsv(evento.conf_capacete),
    formatarPercentualCsv(evento.conf_colete),
    evento.caminho_foto,
  ].map(escaparCsv).join(";"));

  const csv = `\uFEFF${cabecalho.map(escaparCsv).join(";")}\r\n${linhas.join("\r\n")}`;
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "relatorio_conformidade_epis.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  mostrarAvisoExportacao("Relatório CSV exportado com sucesso.");
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
botaoExportarCsv.addEventListener("click", exportarCsv);