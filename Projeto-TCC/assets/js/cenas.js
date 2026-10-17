/* Cenas = uma foto com uma ou mais ocorrências (vários trabalhadores no mesmo frame).
   Agrupa as ocorrências e desenha as caixas de detecção sobre a foto. Lógica
   herdada da galeria anterior; a diferença é que aqui não há acesso ao estado da tela:
   quem chama passa um callback para a seleção de trabalhador. */
import { el } from "./util.js";

// Resolução do frame da câmera usada pelo detector (pixels das caixas).
const LARGURA_FRAME = 720;
const ALTURA_FRAME = 480;

export const statusDe = (ocorrencia) => ocorrencia?.status ?? "pendente";

function lerCaixasBrutas(ocorrencia) {
  const bruto = ocorrencia?.caixas;
  if (!bruto) return null;
  if (typeof bruto === "string") {
    try { return JSON.parse(bruto); } catch { return null; }
  }
  return typeof bruto === "object" ? bruto : null;
}

export function normalizarCaixa(valor) {
  if (!Array.isArray(valor) || valor.length !== 4) return null;
  if (!valor.every((v) => Number.isFinite(Number(v)))) return null;
  return valor.map(Number);
}

export function mesmaCaixa(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== 4 || b.length !== 4) return false;
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
      tipo_infracao: ocorrencia.tipo_infracao,
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

/** Agrupa as ocorrências por foto (cena). A ordem das cenas segue a da lista recebida. */
export function agruparCenas(ocorrencias) {
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

    // Itera pelos TRABALHADORES: a ordem do seletor [#N] fica igual à ordem em
    // que as caixas são desenhadas (o banco devolve as ocorrências em id DESC).
    let selecionaveis = trabalhadores
      .map((trabalhador) => {
        const ocorrencia = cena.ocorrencias.find((atual) =>
          mesmaCaixa(lerCaixasBrutas(atual)?.pessoa, trabalhador.pessoa));
        return ocorrencia ? { ocorrencia, trabalhador } : null;
      })
      .filter(Boolean);

    // Registros sem caixas (dados muito antigos): ainda assim dá para revisar.
    if (selecionaveis.length === 0) {
      selecionaveis = cena.ocorrencias.map((ocorrencia) => ({ ocorrencia, trabalhador: null }));
    }

    cena.trabalhadores = trabalhadores;
    cena.selecionaveis = selecionaveis;
    cena.total_registros = cena.ocorrencias.length;
    return cena;
  });
}

/** Contagem de revisão de uma cena. */
export function resumoRevisao(cena) {
  const contagem = { total: cena.ocorrencias.length, pendente: 0, confirmada: 0, descartada: 0 };
  cena.ocorrencias.forEach((o) => { contagem[statusDe(o)] += 1; });
  return contagem;
}

/* ==========================================================================
   CAIXAS DE DETECÇÃO PROPORCIONAIS À IMAGEM
   ========================================================================== */
function criarCaixaDeteccao(rotulo, caixa, confianca, classeCss, extra = {}) {
  const elemento = el("div", { class: `caixa-deteccao ${classeCss || ""} ${extra.estado || ""}`.trim() });
  if (extra.indice !== undefined && extra.indice !== null) elemento.dataset.trabalhador = String(extra.indice);
  elemento.dataset.caixa = JSON.stringify(caixa);
  if (!extra.semEtiqueta) {
    const semConfianca = confianca === null || confianca === undefined || Number.isNaN(Number(confianca));
    elemento.append(el("span", { class: "caixa-deteccao-rotulo" },
      `${rotulo}${semConfianca ? "" : ` ${(Number(confianca) * 100).toFixed(0)}%`}`));
  }
  return elemento;
}

/** No modo "Todos" desenha só as caixas de pessoa com tag #N; no individual,
 *  pessoa + EPI completos. Dados antigos (sem lista de trabalhadores) caem no 2º ramo. */
function coletarItensCaixa(fonte, modoTodos) {
  if (Array.isArray(fonte?.trabalhadores) && fonte.trabalhadores.length > 0) {
    // O destaque compara a IDENTIDADE da caixa da pessoa ativa, não o índice:
    // `trabalhadores` inclui os conformes, `selecionaveis` só as ocorrências.
    const ativo = fonte.total_registros > 1 && Number.isInteger(fonte.selecionado) && fonte.selecionado >= 0
      ? (fonte.selecionaveis?.[fonte.selecionado]?.trabalhador ?? null)
      : null;

    return fonte.trabalhadores.flatMap((trabalhador, indice) => {
      const estado = fonte.total_registros > 1
        ? (ativo && mesmaCaixa(trabalhador.pessoa, ativo.pessoa) ? "caixa-selecionada" : "caixa-secundaria")
        : "";
      const itens = [{
        rotulo: "Pessoa", tagNumero: `#${indice + 1}`, caixa: trabalhador.pessoa, confianca: trabalhador.conf_pessoa,
        classe: "caixa-pessoa", estado, indice, ehPessoa: true,
      }];
      if (!modoTodos && trabalhador.capacete) {
        itens.push({ rotulo: "Capacete", caixa: trabalhador.capacete, confianca: trabalhador.conf_capacete, classe: "caixa-capacete", estado, indice });
      }
      if (!modoTodos && trabalhador.colete) {
        itens.push({ rotulo: "Colete", caixa: trabalhador.colete, confianca: trabalhador.conf_colete, classe: "caixa-colete", estado, indice });
      }
      return itens;
    });
  }
  return [];
}

function atualizarCaixas(container) {
  // Converte pixels do frame -> imagem natural -> pixels renderizados (object-fit:
  // contain) -> % do container, para as caixas acompanharem qualquer redimensionamento.
  const img = container?.querySelector("img");
  if (!img || !img.naturalWidth) return;
  const largura = container.clientWidth;
  const altura = container.clientHeight;
  if (!largura || !altura) return;

  const escala = Math.min(largura / img.naturalWidth, altura / img.naturalHeight);
  const deslocX = (largura - img.naturalWidth * escala) / 2;
  const deslocY = (altura - img.naturalHeight * escala) / 2;
  const convX = (img.naturalWidth / LARGURA_FRAME) * escala;
  const convY = (img.naturalHeight / ALTURA_FRAME) * escala;

  container.querySelectorAll(".caixa-deteccao").forEach((caixaEl) => {
    const caixa = JSON.parse(caixaEl.dataset.caixa || "null");
    if (!Array.isArray(caixa) || caixa.length !== 4) return;
    const [x1, y1, x2, y2] = caixa.map(Number);
    caixaEl.style.left = `${((deslocX + Math.min(x1, x2) * convX) / largura) * 100}%`;
    caixaEl.style.top = `${((deslocY + Math.min(y1, y2) * convY) / altura) * 100}%`;
    caixaEl.style.width = `${(Math.abs(x2 - x1) * convX * 100) / largura}%`;
    caixaEl.style.height = `${(Math.abs(y2 - y1) * convY * 100) / altura}%`;
  });
}

const observadores = new WeakMap();

/** Desenha as caixas de TODOS os trabalhadores da cena sobre a foto.
 *  opcoes.aoSelecionar(indice) é chamado ao clicar na caixa de uma pessoa. */
export function desenharCaixas(container, cena, { aoSelecionar = null } = {}) {
  if (!container) return;
  container.querySelectorAll(".caixa-deteccao").forEach((no) => no.remove());

  const modoTodos = cena?.modoTodos === true;
  coletarItensCaixa(cena, modoTodos).forEach((item) => {
    if (!item.caixa) return;
    const comTag = modoTodos && item.tagNumero;
    const caixaEl = criarCaixaDeteccao(comTag ? item.tagNumero : item.rotulo, item.caixa,
      modoTodos ? null : item.confianca, item.classe,
      { estado: item.estado, indice: item.indice, semEtiqueta: false });

    if (aoSelecionar && item.ehPessoa) {
      const indiceSelecao = (cena.selecionaveis ?? []).findIndex(
        (entrada) => mesmaCaixa(entrada.trabalhador?.pessoa, item.caixa));
      if (indiceSelecao >= 0) {
        caixaEl.style.pointerEvents = "auto";
        caixaEl.style.cursor = "pointer";
        caixaEl.title = `Selecionar trabalhador ${indiceSelecao + 1}`;
        caixaEl.addEventListener("click", (evento) => {
          evento.stopPropagation();
          aoSelecionar(indiceSelecao);
        });
      }
    }
    container.append(caixaEl);
  });

  const img = container.querySelector("img");
  if (img && !img.complete) img.addEventListener("load", () => atualizarCaixas(container), { once: true });
  atualizarCaixas(container);

  if (!observadores.has(container) && typeof ResizeObserver !== "undefined") {
    const observador = new ResizeObserver(() => atualizarCaixas(container));
    observador.observe(container);
    observadores.set(container, observador);
  }
}
