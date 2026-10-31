import { navegarPara } from "./app.js";
import { formatarDataHora } from "./utils/formatarDataHora.js";
import { formatarCoord } from "./utils/formatarCoord.js";

const galeriaFotos = document.getElementById("galeria-fotos");
const botaoAtualizarFotos = document.getElementById("botao-atualizar");
const botaoVoltarCamera = document.getElementById("voltar-camera");
const imagemAmpliada = document.getElementById("foto-ampliada");
const botaoFecharImagemAmpliada = document.getElementById("fechar-dados-imagem");
const botaoDeletar = document.getElementById("botao-deletar-foto");
const botaoConfirmaApagar = document.getElementById("botao-apagar");
const botaoCancelaApagar = document.getElementById("botao-cancelar");
const mensagemStatusApagar = document.getElementById("mensagem-status-apagar");

let fotoSelecionada = null;

export async function carregarFotos() {
  const resposta = await fetch("/listar_ocorrencias");

  if (!resposta.ok) {
    // Mantém a mensagem de "galeria vazia" visível em caso de falha.
    galeriaFotos.innerHTML = "";
    return;
  }
  const dadosFoto = await resposta.json();
  filtrarDados(dadosFoto);
}

function filtrarDados(dadosFoto) {
  //Limpa a galeria para as fotos atualizadas aparecerem
  galeriaFotos.innerHTML = "";
  
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
    data.innerText = `#${dado.id} · ${formatarDataHora(dado.timestamp)}`;

    info.appendChild(tipo);
    info.appendChild(data);

    card.appendChild(badge);
    card.appendChild(foto);
    card.appendChild(info);

    // Abre o modal de detalhes ao clicar em qualquer parte do cartão.
    card.addEventListener("click", () => {
      mostrarDetalhesFoto(dado);
      desenharCaixa(dado);
    });

    galeriaFotos.appendChild(card);
  });
}

function mostrarDetalhesFoto(dado) {
  imagemAmpliada.src = `/foto/${dado.caminho_foto}`;
  fotoSelecionada = dado;
  
  inserirDadosFoto(dado);
}

function inserirDadosFoto(dado) {
  const dataFormatada = formatarDataHora(dado.timestamp);
  document.getElementById("data-infracao").innerText = dataFormatada;

  document.getElementById("tipo-infracao").innerText = dado.tipo_infracao;

  const posicaoXFormatada = formatarCoord(dado.posicao_x);
  const posicaoYFormatada = formatarCoord(dado.posicao_y);
  document.getElementById("posicaox-infracao").innerText = posicaoXFormatada;
  document.getElementById("posicaoy-infracao").innerText = posicaoYFormatada;

  aplicarBarraConfianca("confiancap-infracao", "barra-conf-pessoa", dado.conf_pessoa);
  aplicarBarraConfianca("confiancacp-infracao", "barra-conf-capacete", dado.conf_capacete);
  aplicarBarraConfianca("confiancacl-infracao", "barra-conf-colete", dado.conf_colete);

  document.getElementById("mostrar-dados-imagem").style.display = "block";
}

// Fecha o modal de detalhes ao clicar no fundo escurecido (overlay).
document.getElementById("mostrar-dados-imagem").addEventListener("click", (e) => {
  if (e.target.id === "mostrar-dados-imagem") {
    document.getElementById("mostrar-dados-imagem").style.display = "none";
  }
});

async function deletarFoto(dado) {
  
  /*
  No FastAPI, parâmetros de funções em 
  rotas sem chaves no caminho são recebidos
  como Query Parameters (parâmetros de 
  URL com /rota?chave=valor&chave2=valor2).
  */

  const nome_foto = dado.caminho_foto;
  const id = dado.id;

  const url = `/excluir_ocorrencias?imagem_deletar=${nome_foto}&id=${id}`;
  const resposta = await fetch(url, {
    method: "DELETE"
  });

  if (resposta.ok) {
    document.getElementById("permissao-apagar").style.display = "none";
    document.getElementById("mostrar-dados-imagem").style.display = "none";

    fotoSelecionada = null;
    carregarFotos();

    mensagemStatusApagar.className = "status-sucesso";
    mensagemStatusApagar.innerHTML = `
      <svg class="ic ic-status" aria-hidden="true"><use href="icones.svg#confere" /></svg>
      <span>Imagem apagada com sucesso</span>
    `;
    setTimeout(() => {
      mensagemStatusApagar.innerHTML = "";
      mensagemStatusApagar.className = "";
    }, 2500);

  }
  else {
    mensagemStatusApagar.className = "status-erro";
    mensagemStatusApagar.innerHTML = `
      <svg class="ic ic-status" aria-hidden="true"><use href="icones.svg#x" /></svg>
      <span>Erro ao tentar apagar a imagem</span>
    `;
    document.getElementById("permissao-apagar").style.display = "none";
    document.getElementById("mostrar-dados-imagem").style.display = "none";

    setTimeout(() => {
      mensagemStatusApagar.innerHTML = "";
      mensagemStatusApagar.className = "";
    }, 2500);
  }
}

function aplicarBarraConfianca(idValor, idBarra, valor) {
  const rotulo = document.getElementById(idValor);
  const barra = document.getElementById(idBarra);
  if (!rotulo || !barra) return;

  if (valor === null || valor === undefined || isNaN(valor)) {
    rotulo.innerText = "--";
    barra.style.width = "0%";
    barra.className = "conf-trilha-barra"; // ou limpa as classes
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

function desenharCaixa(dado) {
  
  const caixa = dado.caixa_operario;
  const canvas = document.getElementById("canvas-foto");
  const ctx = canvas.getContext("2d");
  const img = document.getElementById("foto-ampliada");

  canvas.width = img.clientWidth;
  canvas.height = img.clientHeight;

  ctx.clearRect(0, 0, canvas.width, canvas.height);

  if (!caixa) return;

  const [x1, y1, x2, y2] = JSON.parse(caixa);

  const escalaX = canvas.width / 720;
  const escalaY = canvas.height / 480;

  const x = x1 * escalaX;
  const y = y1 * escalaY;
  const largura = (x2 - x1) * escalaX;
  const altura = (y2 - y1) * escalaY;

  ctx.strokeStyle = "#ff0000";
  ctx.lineWidth = 3;
  ctx.strokeRect(x, y, largura, altura);
}

botaoDeletar.addEventListener("click", () => {
  document.getElementById("permissao-apagar").style.display = "block";
});
botaoConfirmaApagar.addEventListener("click", () => {
  if (fotoSelecionada) {
    deletarFoto(fotoSelecionada);
  }
});
botaoCancelaApagar.addEventListener("click", () => {
  document.getElementById("permissao-apagar").style.display = "none";
  document.getElementById("mostrar-dados-imagem").style.display = "none";
});

botaoFecharImagemAmpliada.addEventListener("click", () => {
  document.getElementById("mostrar-dados-imagem").style.display = "none";
  document.getElementById("permissao-apagar").style.display = "none";

  fotoSelecionada = null;
});

botaoAtualizarFotos.addEventListener("click", carregarFotos);

botaoVoltarCamera.addEventListener("click", () => navegarPara("painel"));