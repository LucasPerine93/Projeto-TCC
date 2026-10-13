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

    const moldura = document.createElement("div");
    moldura.className = "foto-media";

    const foto = document.createElement("img");
    foto.src = `/foto/${dado.caminho_foto}`;
    foto.alt = `Evidência: ${dado.tipo_infracao}`;
    foto.loading = "lazy";

    moldura.appendChild(foto);
    desenharCaixas(moldura, dado);

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
    card.appendChild(moldura);
    card.appendChild(info);

    // Abre o modal de detalhes ao clicar em qualquer parte do cartão.
    card.addEventListener("click", () => {
      mostrarDetalhesFoto(dado);
    });

    galeria_fotos.appendChild(card);
  });
}

botaoAtualizarFotos.addEventListener("click", carregarFotos);


/* ==========================================================================
   CAIXAS DE DETECÇÃO (BOUNDING BOXES) PROPORCIONAIS À IMAGEM
   ========================================================================== */
// Resolução do frame da câmera usada pelo detector (pixels das caixas).
const LARGURA_FRAME = 720;
const ALTURA_FRAME = 480;

function interpretarCaixas(ocorrencia) {
  // Normaliza o campo "caixas" (JSON ou dicionário) para {pessoa, capacete, colete}.
  const bruto = ocorrencia?.caixas;
  if (!bruto) return null;
  let caixas = bruto;
  if (typeof caixas === "string") {
    try {
      caixas = JSON.parse(caixas);
    } catch (e) {
      return null;
    }
  }
  if (!caixas || typeof caixas !== "object") return null;
  const normalizar = (valor) =>
    Array.isArray(valor) && valor.length === 4 && valor.every((v) => Number.isFinite(Number(v)))
      ? valor.map(Number)
      : null;
  return {
    pessoa: normalizar(caixas.pessoa),
    capacete: normalizar(caixas.capacete),
    colete: normalizar(caixas.colete),
  };
}

function criarCaixaDeteccao(rotulo, caixa, confianca, classeCss) {
  // Cria o retângulo. O posicionamento (% da imagem renderida) é feito
  // posteriormente em atualizarCaixas(), quando a imagem já tem dimensões.
  const elemento = document.createElement("div");
  elemento.className = `caixa-deteccao ${classeCss || ""}`.trim();
  elemento.dataset.caixa = JSON.stringify(caixa);
  const etiqueta = document.createElement("span");
  etiqueta.className = "caixa-deteccao-rotulo";
  const textoConfianca =
    confianca === null || confianca === undefined || Number.isNaN(Number(confianca))
      ? ""
      : ` ${(Number(confianca) * 100).toFixed(0)}%`;
  etiqueta.textContent = `${rotulo}${textoConfianca}`;
  elemento.appendChild(etiqueta);
  return elemento;
}

function atualizarCaixas(container) {
  // Reposiciona as caixas em % com base na resolução REAL da imagem
  // (naturalWidth/naturalHeight) e no tamanho renderido na tela
  // (clientWidth/clientHeight da moldura), incluindo as barras laterais do
  // object-fit: contain. Assim, qualquer redimensionamento (modal, janela,
  // responsivo) mantém as caixas exatamente sobre os objetos da foto.
  if (!container) return;
  const img = container.querySelector("img");
  if (!img || !img.naturalWidth) return;
  const cliW = container.clientWidth;
  const cliH = container.clientHeight;
  if (!cliW || !cliH) return;

  // Área efetiva da imagem dentro da moldura (contain = escala uniforme).
  const escala = Math.min(cliW / img.naturalWidth, cliH / img.naturalHeight);
  const offX = (cliW - img.naturalWidth * escala) / 2;
  const offY = (cliH - img.naturalHeight * escala) / 2;

  // As caixas vêm em pixels do frame da câmera; converte frame -> imagem
  // natural -> pixels renderidos, e por fim em % do container.
  const convX = (img.naturalWidth / LARGURA_FRAME) * escala;
  const convY = (img.naturalHeight / ALTURA_FRAME) * escala;

  container.querySelectorAll(".caixa-deteccao").forEach((el) => {
    const caixa = JSON.parse(el.dataset.caixa || "null");
    if (!Array.isArray(caixa) || caixa.length !== 4) return;
    const [x1, y1, x2, y2] = caixa.map(Number);
    const esquerda = Math.min(x1, x2);
    const topo = Math.min(y1, y2);
    el.style.left = `${((offX + esquerda * convX) / cliW) * 100}%`;
    el.style.top = `${((offY + topo * convY) / cliH) * 100}%`;
    el.style.width = `${(Math.abs(x2 - x1) * convX * 100) / cliW}%`;
    el.style.height = `${(Math.abs(y2 - y1) * convY * 100) / cliH}%`;
  });
}

// Um único ResizeObserver por moldura, para reposicionar ao redimensionar.
const observadoresCaixas = new WeakMap();

function desenharCaixas(container, ocorrencia) {
  // Desenha as caixas da pessoa/capacete/colete sobre a imagem exibida.
  if (!container) return;
  container.querySelectorAll(".caixa-deteccao").forEach((el) => el.remove());
  const caixas = interpretarCaixas(ocorrencia);
  if (!caixas) return;
  const itens = [
    { rotulo: "Pessoa", caixa: caixas.pessoa, confianca: ocorrencia?.conf_pessoa, classe: "caixa-pessoa" },
    { rotulo: "Capacete", caixa: caixas.capacete, confianca: ocorrencia?.conf_capacete, classe: "caixa-capacete" },
    { rotulo: "Colete", caixa: caixas.colete, confianca: ocorrencia?.conf_colete, classe: "caixa-colete" },
  ];
  itens.forEach(({ rotulo, caixa, confianca, classe }) => {
    if (!caixa) return;
    container.appendChild(criarCaixaDeteccao(rotulo, caixa, confianca, classe));
  });

  // Posiciona quando a imagem estiver decodificada (naturalWidth disponível).
  const img = container.querySelector("img");
  if (img && !img.complete) {
    img.addEventListener("load", () => atualizarCaixas(container), { once: true });
  }
  atualizarCaixas(container);

  // Acompanha qualquer redimensionamento da moldura (modal/janela/responsivo).
  if (!observadoresCaixas.has(container) && typeof ResizeObserver !== "undefined") {
    const observador = new ResizeObserver(() => atualizarCaixas(container));
    observador.observe(container);
    observadoresCaixas.set(container, observador);
  }
}


function mostrarDetalhesFoto(dado) {
  imagemAmpliada.src = `/foto/${dado.caminho_foto}`;
  desenharCaixas(document.getElementById("foto-moldura"), dado);

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