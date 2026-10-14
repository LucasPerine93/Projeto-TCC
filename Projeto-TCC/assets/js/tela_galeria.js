import { mostrarTela, estado } from "./app.js";
import { aplicarBarraConfianca } from "./tela_dashboard.js";

const galeria_fotos = document.getElementById("galeria-fotos");
const botaoAtualizarFotos = document.getElementById("botao-atualizar");
const botaoVoltarCamera = document.getElementById("voltar-camera");
const imagemAmpliada = document.getElementById("foto-ampliada");
const botaoFecharImagemAmpliada = document.getElementById("fechar-dados-imagem");
const botaoDescartarOcorrencia = document.getElementById("descartar-ocorrencia");
const textoDescartarOcorrencia = document.getElementById("texto-descartar-ocorrencia");
const botoesFiltro = [...document.querySelectorAll(".filtro-galeria")];

let ocorrenciasGaleria = [];
let cenasGaleria = [];
let filtroAtivo = "Todas";
let cenaAberta = null;
let trabalhadorSelecionado = 0;

/* ==========================================================================
   AGRUPAMENTO POR CENA
   ==========================================================================
   Várias ocorrências podem compartilhar a mesma fotografia. A galeria mostra
   UM cartão por foto e o modal permite alternar entre os trabalhadores
   registrados naquela cena. Dados antigos (uma ocorrência por foto) continuam
   funcionando: cada ocorrência vira a sua própria cena. */

function lerCaixasBrutas(ocorrencia) {
  const bruto = ocorrencia?.caixas;
  if (!bruto) return null;
  if (typeof bruto === "string") {
    try {
      return JSON.parse(bruto);
    } catch (e) {
      return null;
    }
  }
  return typeof bruto === "object" ? bruto : null;
}

function mesmaCaixa(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== 4 || b.length !== 4) {
    return false;
  }
  return a.every((valor, indice) => Number(valor) === Number(b[indice]));
}

/** Une os trabalhadores de todas as ocorrências que compartilham a foto. */
function montarTrabalhadores(ocorrencias) {
  const trabalhadores = [];

  const adicionar = (trabalhador) => {
    if (!trabalhador) return;
    const pessoa = normalizarCaixa(trabalhador.pessoa);
    if (!pessoa) return;
    if (trabalhadores.some((atual) => mesmaCaixa(atual.pessoa, pessoa))) return;
    trabalhadores.push({
      track_id: trabalhador.track_id ?? null,
      tipo_infracao: trabalhador.tipo_infracao ?? null,
      risco_detectado: Boolean(trabalhador.risco_detectado),
      conf_pessoa: trabalhador.conf_pessoa ?? null,
      conf_capacete: trabalhador.conf_capacete ?? null,
      conf_colete: trabalhador.conf_colete ?? null,
      pessoa,
      capacete: normalizarCaixa(trabalhador.capacete),
      colete: normalizarCaixa(trabalhador.colete),
    });
  };

  ocorrencias.forEach((ocorrencia) => {
    const caixas = lerCaixasBrutas(ocorrencia);
    const lista = Array.isArray(caixas?.operarios) ? caixas.operarios : [];
    if (lista.length > 0) {
      lista.forEach(adicionar);
      return;
    }
    // Retrocompatibilidade: sem "operarios", a própria ocorrência é o trabalhador.
    adicionar({
      track_id: null,
      tipo_infracao: ocorrencia.tipo_infracao,
      risco_detectado: false,
      conf_pessoa: ocorrencia.conf_pessoa,
      conf_capacete: ocorrencia.conf_capacete,
      conf_colete: ocorrencia.conf_colete,
      pessoa: caixas?.pessoa,
      capacete: caixas?.capacete,
      colete: caixas?.colete,
    });
  });

  return trabalhadores;
}

function agruparCenas(ocorrencias) {
  const cenas = new Map();

  ocorrencias.forEach((ocorrencia) => {
    const caixas = lerCaixasBrutas(ocorrencia);
    const chave = caixas?.cena_id || ocorrencia.caminho_foto || `id-${ocorrencia.id}`;

    if (!cenas.has(chave)) {
      cenas.set(chave, {
        chave,
        caminho_foto: ocorrencia.caminho_foto,
        cena_id: caixas?.cena_id ?? null,
        timestamp: ocorrencia.timestamp,
        ocorrencias: [],
      });
    }
    cenas.get(chave).ocorrencias.push(ocorrencia);
  });

  return [...cenas.values()].map((cena) => {
    const trabalhadores = montarTrabalhadores(cena.ocorrencias);

    // Liga cada ocorrência registrada ao trabalhador correspondente na cena.
    cena.selecionaveis = cena.ocorrencias.map((ocorrencia) => {
      const caixas = lerCaixasBrutas(ocorrencia);
      const proprio = trabalhadores.find((trabalhador) =>
        mesmaCaixa(trabalhador.pessoa, caixas?.pessoa),
      );
      return {
        ocorrencia,
        trabalhador: proprio || trabalhadores[0] || null,
      };
    });

    cena.trabalhadores = trabalhadores;
    cena.total_registros = cena.ocorrencias.length;
    return cena;
  });
}



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

  ocorrenciasGaleria = Array.isArray(dadosFoto) ? dadosFoto : [];
  cenasGaleria = agruparCenas(ocorrenciasGaleria);
  atualizarContadoresFiltros();
  renderizarGaleria();
}

function atualizarContadoresFiltros() {
  botoesFiltro.forEach((botao) => {
    const filtro = botao.dataset.filtro;
    const total = filtro === "Todas"
      ? ocorrenciasGaleria.length
      : ocorrenciasGaleria.filter((dado) => dado.tipo_infracao === filtro).length;
    const contador = botao.querySelector("[data-contador-filtro]");
    if (contador) contador.innerText = total;
  });
}

function renderizarGaleria() {
  galeria_fotos.innerHTML = "";

  if (cenasGaleria.length === 0) {
    const vazio = document.createElement("p");
    vazio.className = "estado-vazio-galeria";
    vazio.innerText = "Nenhuma ocorrência registrada no momento.";
    galeria_fotos.appendChild(vazio);
    return;
  }

  // Filtro por tipo: uma cena entra se algum registro dela for do tipo.
  const cenasFiltradas = filtroAtivo === "Todas"
    ? cenasGaleria
    : cenasGaleria.filter((cena) =>
        cena.ocorrencias.some((dado) => dado.tipo_infracao === filtroAtivo));

  if (cenasFiltradas.length === 0) {
    const vazio = document.createElement("p");
    vazio.className = "estado-vazio-galeria";
    vazio.innerText = "Nenhuma ocorrência encontrada para este filtro.";
    galeria_fotos.appendChild(vazio);
    return;
  }

  // UM cartão por fotografia, mesmo com vários trabalhadores na cena.
  cenasFiltradas.forEach((cena) => {
    const card = document.createElement("figure");
    card.className = "foto-card";

    const badge = document.createElement("span");
    badge.className = "foto-card-badge";
    badge.innerHTML = '<svg class="ic" aria-hidden="true"><use href="icones.svg#camera" /></svg>';

    const moldura = document.createElement("div");
    moldura.className = "foto-media";

    const foto = document.createElement("img");
    foto.src = `/foto/${cena.caminho_foto}`;
    foto.alt = `Evidência com ${cena.total_registros} ocorrência(s) na cena`;
    foto.loading = "lazy";
    moldura.appendChild(foto);

    // Desenha TODOS os trabalhadores da cena sobre a mesma foto.
    desenharCaixas(moldura, cena);

    const info = document.createElement("figcaption");
    info.className = "foto-card-info";

    const tipos = [...new Set(cena.ocorrencias.map((dado) => dado.tipo_infracao))];
    const tipo = document.createElement("span");
    tipo.className = "foto-card-tipo";
    tipo.innerText = tipos.join(" + ");

    const data = document.createElement("span");
    data.className = "foto-card-data";
    data.innerText = `#${cena.ocorrencias[0].id} · ${new Date(cena.timestamp).toLocaleString("pt-BR")}`;

    info.appendChild(tipo);
    info.appendChild(data);

    // Indicador de múltiplos trabalhadores na mesma fotografia.
    if (cena.total_registros > 1) {
      const selo = document.createElement("span");
      selo.className = "foto-card-cena";
      selo.innerText = `${cena.total_registros} ocorrências na cena`;
      info.appendChild(selo);
    }

    card.appendChild(badge);
    card.appendChild(moldura);
    card.appendChild(info);

    // Abre o modal de detalhes ao clicar em qualquer parte do cartão.
    card.addEventListener("click", () => abrirDetalhesCena(cena));

    galeria_fotos.appendChild(card);
  });
}

botaoAtualizarFotos.addEventListener("click", carregarFotos);
botoesFiltro.forEach((botao) => {
  botao.addEventListener("click", () => {
    filtroAtivo = botao.dataset.filtro;
    botoesFiltro.forEach((item) => item.classList.toggle("ativo", item === botao));
    renderizarGaleria();
  });
});


/* ==========================================================================
   CAIXAS DE DETECÇÃO (BOUNDING BOXES) PROPORCIONAIS À IMAGEM
   ========================================================================== */
// Resolução do frame da câmera usada pelo detector (pixels das caixas).
const LARGURA_FRAME = 720;
const ALTURA_FRAME = 480;

// Converte uma caixa em 4 números finitos, ou null quando inválida.
function normalizarCaixa(valor) {
  if (!Array.isArray(valor) || valor.length !== 4) return null;
  if (!valor.every((v) => Number.isFinite(Number(v)))) return null;
  return valor.map(Number);
}

function interpretarCaixas(ocorrencia) {
  // Normaliza o campo "caixas" (JSON ou dicionário) para {pessoa, capacete, colete}.
  const caixas = lerCaixasBrutas(ocorrencia);
  if (!caixas) return null;
  return {
    pessoa: normalizarCaixa(caixas.pessoa),
    capacete: normalizarCaixa(caixas.capacete),
    colete: normalizarCaixa(caixas.colete),
  };
}

function criarCaixaDeteccao(rotulo, caixa, confianca, classeCss, extra) {
  // Cria o retângulo. O posicionamento (% da imagem renderida) é feito
  // posteriormente em atualizarCaixas(), quando a imagem já tem dimensões.
  const opcoes = extra || {};
  const elemento = document.createElement("div");
  elemento.className = `caixa-deteccao ${classeCss || ""}`.trim();
  if (opcoes.estado) elemento.classList.add(opcoes.estado);
  if (opcoes.indice !== undefined && opcoes.indice !== null) {
    elemento.dataset.trabalhador = String(opcoes.indice);
  }
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

/** Itens de caixa a desenhar: todos os trabalhadores da cena. */
function coletarItensCaixa(fonte) {
  if (Array.isArray(fonte?.trabalhadores)) {
    return fonte.trabalhadores.flatMap((trabalhador, indice) => {
      const estado =
        fonte.total_registros > 1
          ? indice === fonte.selecionado ? "caixa-selecionada" : "caixa-secundaria"
          : "";
      const itens = [{
        rotulo: "Pessoa",
        caixa: trabalhador.pessoa,
        confianca: trabalhador.conf_pessoa,
        classe: "caixa-pessoa",
        estado,
        indice,
        ehPessoa: true,
      }];
      if (trabalhador.capacete) {
        itens.push({
          rotulo: "Capacete", caixa: trabalhador.capacete,
          confianca: trabalhador.conf_capacete, classe: "caixa-capacete", estado, indice,
        });
      }
      if (trabalhador.colete) {
        itens.push({
          rotulo: "Colete", caixa: trabalhador.colete,
          confianca: trabalhador.conf_colete, classe: "caixa-colete", estado, indice,
        });
      }
      return itens;
    });
  }

  // Dados antigos (uma ocorrência por foto): desenha só aquele trabalhador.
  const caixas = interpretarCaixas(fonte);
  if (!caixas) return [];
  const itens = [{
    rotulo: "Pessoa", caixa: caixas.pessoa, confianca: fonte?.conf_pessoa,
    classe: "caixa-pessoa", estado: "", indice: 0, ehPessoa: true,
  }];
  if (caixas.capacete) {
    itens.push({
      rotulo: "Capacete", caixa: caixas.capacete,
      confianca: fonte?.conf_capacete, classe: "caixa-capacete", estado: "", indice: 0,
    });
  }
  if (caixas.colete) {
    itens.push({
      rotulo: "Colete", caixa: caixas.colete,
      confianca: fonte?.conf_colete, classe: "caixa-colete", estado: "", indice: 0,
    });
  }
  return itens;
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

function desenharCaixas(container, fonte, permitirSelecao = false) {
  // Desenha as caixas de TODOS os trabalhadores da cena sobre a imagem.
  // ``fonte`` pode ser uma cena (com ``trabalhadores``) ou uma ocorrência
  // avulsa (retrocompatibilidade).
  if (!container) return;
  container.querySelectorAll(".caixa-deteccao").forEach((el) => el.remove());

  coletarItensCaixa(fonte).forEach((item) => {
    if (!item.caixa) return;
    const elemento = criarCaixaDeteccao(item.rotulo, item.caixa, item.confianca, item.classe, {
      estado: item.estado,
      indice: item.indice,
    });

    // Clicar na caixa da pessoa seleciona aquele trabalhador.
    if (permitirSelecao && item.ehPessoa && item.indice !== undefined && item.indice !== null) {
      elemento.style.cursor = "pointer";
      elemento.title = `Selecionar Trabalhador ${item.indice + 1}`;
      elemento.addEventListener("click", (evento) => {
        evento.stopPropagation();
        selecionarTrabalhador(item.indice);
      });
    }

    container.appendChild(elemento);
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


function montarSeletorTrabalhador() {
  const painel = document.getElementById("seletor-trabalhador");
  const botoes = document.getElementById("seletor-trabalhador-botoes");
  if (!painel || !botoes || !cenaAberta) return;

  botoes.innerHTML = "";
  const total = cenaAberta.total_registros;
  painel.hidden = total <= 1;

  cenaAberta.selecionaveis.forEach((item, indice) => {
    const botao = document.createElement("button");
    botao.type = "button";
    botao.className = `seletor-botao${indice === cenaAberta.selecionado ? " ativo" : ""}`;
    botao.innerText = `Trabalhador ${indice + 1}`;
    botao.addEventListener("click", (evento) => {
      evento.stopPropagation();
      selecionarTrabalhador(indice);
    });
    botoes.appendChild(botao);
  });
}

function preencherDetalhes(item) {
  const dado = item?.ocorrencia;
  if (!dado) return;

  document.getElementById("data-infracao").innerText = new Date(dado.timestamp).toLocaleString("pt-BR");
  document.getElementById("tipo-infracao").innerText = dado.tipo_infracao;
  document.getElementById("posicaox-infracao").innerText = dado.posicao_x?.toFixed(1) ?? "--";
  document.getElementById("posicaoy-infracao").innerText = dado.posicao_y?.toFixed(1) ?? "--";

  // Confianças do trabalhador selecionado (a da ocorrência registrada).
  const trabalhador = item.trabalhador;
  aplicarBarraConfianca("confiancap-infracao", "barra-conf-pessoa", dado.conf_pessoa);
  aplicarBarraConfianca("confiancacp-infracao", "barra-conf-capacete", dado.conf_capacete);
  aplicarBarraConfianca("confiancacl-infracao", "barra-conf-colete", dado.conf_colete);

  // Mantém os dados do trabalhador disponíveis para o rótulo do descarte.
  botaoDescartarOcorrencia.dataset.ocorrenciaId = String(dado.id ?? "");
  botaoDescartarOcorrencia.hidden = !dado.id;
  if (trabalhador) {
    document.getElementById("tipo-infracao").title =
      trabalhador.risco_detectado ? "Também detectado em área de risco" : "";
  }
}

export function abrirDetalhesCena(cena, indiceInicial = 0) {
  if (!cena) return;
  cenaAberta = cena;
  cena.selecionado = indiceInicial;

  const moldura = document.getElementById("foto-moldura");
  imagemAmpliada.src = `/foto/${cena.caminho_foto}`;
  desenharCaixas(moldura, cena, true);

  montarSeletorTrabalhador();
  preencherDetalhes(cena.selecionaveis[indiceInicial]);

  document.getElementById("mostrar-dados-imagem").style.display = "block";
}

/** Troca o trabalhador em exibição sem recarregar a página. */
export function selecionarTrabalhador(indice) {
  if (!cenaAberta) return;
  const item = cenaAberta.selecionaveis[indice];
  if (!item) return;

  cenaAberta.selecionado = indice;

  // Redesenha para atualizar o destaque das caixas.
  desenharCaixas(document.getElementById("foto-moldura"), cenaAberta, true);

  montarSeletorTrabalhador();
  preencherDetalhes(item);
}

/** Abre o modal a partir de uma ocorrência (usado pela tabela do dashboard). */
export function abrirDetalhesOcorrencia(ocorrencia) {
  if (!ocorrencia) return;
  const cena = cenasGaleria.find((atual) =>
    atual.ocorrencias.some((dado) => dado.id === ocorrencia.id));
  if (!cena) return;

  const indice = cena.selecionaveis.findIndex(
    (item) => item.ocorrencia.id === ocorrencia.id,
  );
  abrirDetalhesCena(cena, Math.max(0, indice));
}

async function descartarOcorrenciaAberta() {
  const item = cenaAberta?.selecionaveis[cenaAberta.selecionado];
  const ocorrencia = item?.ocorrencia;
  if (!ocorrencia?.id) return;

  const outrasNaCena = cenaAberta.total_registros > 1;
  const pergunta = outrasNaCena
    ? "Descartar esta ocorrência? As demais ocorrências da mesma foto serão mantidas."
    : "Descartar esta ocorrência? A foto de evidência também será removida.";
  if (!window.confirm(pergunta)) return;

  botaoDescartarOcorrencia.disabled = true;
  const textoOriginal = textoDescartarOcorrencia.innerText;
  textoDescartarOcorrencia.innerText = "Descartando...";
  try {
    const resposta = await fetch(`/excluir_ocorrencia/${encodeURIComponent(ocorrencia.id)}`, {
      method: "POST",
    });
    const resultado = await resposta.json().catch(() => ({}));
    if (!resposta.ok || !resultado.sucesso) {
      throw new Error(resultado.mensagem || "Não foi possível descartar a ocorrência.");
    }

    document.getElementById("mostrar-dados-imagem").style.display = "none";
    cenaAberta = null;
    await carregarFotos();
    const { carregarDashboard } = await import("./tela_dashboard.js");
    await carregarDashboard();
  } catch (erro) {
    console.error("Erro ao descartar ocorrência:", erro);
    window.alert(erro.message || "Não foi possível descartar a ocorrência.");
  } finally {
    botaoDescartarOcorrencia.disabled = false;
    textoDescartarOcorrencia.innerText = textoOriginal;
  }
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

botaoDescartarOcorrencia.addEventListener("click", descartarOcorrenciaAberta);

botaoVoltarCamera.addEventListener("click", () => {
  estado.telaAtual = "camera";
  mostrarTela();
});