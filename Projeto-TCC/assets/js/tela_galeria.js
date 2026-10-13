import { mostrarTela, estado } from "./app.js";
import { aplicarBarraConfianca } from "./tela_dashboard.js";

const galeria_fotos = document.getElementById("galeria-fotos");
const botaoAtualizarFotos = document.getElementById("botao-atualizar");
const botaoVoltarCamera = document.getElementById("voltar-camera");
const imagemAmpliada = document.getElementById("foto-ampliada");
const botaoFecharImagemAmpliada = document.getElementById("fechar-dados-imagem");


export async function carregarFotos() {
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
    badge.innerHTML = '<svg class="ic" aria-hidden="true"><use href="icones.svg#camera" /></svg>';

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
  estado.telaAtual = "camera";
  mostrarTela();
});