/* Utilitários de DOM, texto e datas (sem dependências). */

/** Cria um elemento sem usar innerHTML (textos sempre entram como texto). */
export function el(tag, atributos = {}, ...filhos) {
  const no = document.createElement(tag);
  for (const [chave, valor] of Object.entries(atributos)) {
    if (valor === null || valor === undefined || valor === false) continue;
    if (chave === "class") no.className = valor;
    else if (chave === "dataset") Object.assign(no.dataset, valor);
    else if (chave.startsWith("on")) no.addEventListener(chave.slice(2), valor);
    else no.setAttribute(chave, valor === true ? "" : String(valor));
  }
  for (const filho of filhos.flat()) {
    if (filho === null || filho === undefined || filho === false) continue;
    no.append(filho instanceof Node ? filho : document.createTextNode(String(filho)));
  }
  return no;
}

/** Ícone do sprite icones.svg. */
export function icone(nome) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "ic");
  svg.setAttribute("aria-hidden", "true");
  const uso = document.createElementNS(NS, "use");
  uso.setAttribute("href", `icones.svg#${nome}`);
  svg.appendChild(uso);
  return svg;
}

export const normalizar = (texto) =>
  String(texto ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();

/* O detector grava "Invasao de area de risco" (sem acento); dados antigos podem ter
   acento. A chave normalizada junta tudo sob um único rótulo. */
const TIPOS = {
  "sem capacete e colete": { rotulo: "Sem capacete e colete", gravidade: "critico" },
  "sem capacete": { rotulo: "Sem capacete", gravidade: "critico" },
  "sem colete": { rotulo: "Sem colete", gravidade: "atencao" },
  "invasao de area de risco": { rotulo: "Invasão de área de risco", gravidade: "critico" },
  "com capacete e colete": { rotulo: "Conforme", gravidade: "ok" },
};
export const TIPOS_CONHECIDOS = [
  "Sem capacete", "Sem colete", "Sem capacete e colete", "Invasão de área de risco",
];
const ROTULO_GRAVIDADE = { critico: "Crítico", atencao: "Atenção", ok: "Conforme", neutro: "Outro" };
const ICONE_GRAVIDADE = { critico: "x", atencao: "aviso", ok: "ok", neutro: "aviso" };
const ORDEM_GRAVIDADE = { critico: 0, atencao: 1, neutro: 2, ok: 3 };

export function infoTipo(tipo) {
  const dado = TIPOS[normalizar(tipo)];
  return dado ?? { rotulo: String(tipo ?? "—"), gravidade: "neutro" };
}
export const ordemGravidade = (g) => ORDEM_GRAVIDADE[g] ?? 9;
export const iconeGravidade = (g) => ICONE_GRAVIDADE[g] ?? "aviso";

/** Selo "ícone + texto" (a cor nunca é o único sinal). */
export function pilulaTipo(tipo, { comGravidade = true } = {}) {
  const info = infoTipo(tipo);
  const filhos = [icone(iconeGravidade(info.gravidade))];
  if (comGravidade && info.gravidade !== "neutro") {
    filhos.push(el("span", { class: "sr-only" }, `${ROTULO_GRAVIDADE[info.gravidade]}: `));
  }
  filhos.push(info.rotulo);
  return el("span", { class: `pilula p-${info.gravidade}` }, filhos);
}

export function pilulaStatus(status) {
  const mapa = {
    pendente: ["p-neutro", "lista", "Pendente"],
    confirmada: ["p-critico", "ok", "Confirmada"],
    descartada: ["p-ok", "x", "Falso positivo"],
  };
  const [classe, nome, texto] = mapa[status] ?? mapa.pendente;
  return el("span", { class: `pilula ${classe}` }, icone(nome), texto);
}

const doisDigitos = (n) => String(n).padStart(2, "0");
export const hora = (d) => `${doisDigitos(d.getHours())}:${doisDigitos(d.getMinutes())}`;

export function dataHoraCompleta(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("pt-BR");
}

/** "Hoje 09:12", "Ontem 16:05" ou "13/10 09:40". */
export function dataHoraRelativa(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const meiaNoite = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const dias = Math.round((meiaNoite(new Date()) - meiaNoite(d)) / 86400000);
  if (dias === 0) return `Hoje ${hora(d)}`;
  if (dias === 1) return `Ontem ${hora(d)}`;
  return `${doisDigitos(d.getDate())}/${doisDigitos(d.getMonth() + 1)} ${hora(d)}`;
}

/** Início (00:00) do período em dias de calendário; dias=1 é hoje. */
export function inicioDoPeriodo(dias) {
  const agora = new Date();
  return new Date(agora.getFullYear(), agora.getMonth(), agora.getDate() - (Number(dias) - 1));
}

/** Região do quadro (frame de 720 px) em palavras, no lugar de coordenadas. */
export function regiaoDoQuadro(x, largura = 720) {
  if (!Number.isFinite(Number(x))) return "—";
  const terco = largura / 3;
  if (x < terco) return "Lado esquerdo";
  if (x < 2 * terco) return "Centro";
  return "Lado direito";
}

export function formatarPercentual(valor) {
  if (valor === null || valor === undefined || Number.isNaN(Number(valor))) return "—";
  return `${Number(valor).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
}

export function plural(n, singular, pluralTexto) {
  return `${n} ${n === 1 ? singular : pluralTexto ?? singular + "s"}`;
}

/** localStorage/sessionStorage podem lançar exceção (modo privado): sempre com try/catch. */
export function lerPreferencia(chave, padrao = null) {
  try { return localStorage.getItem(chave) ?? padrao; } catch { return padrao; }
}
export function gravarPreferencia(chave, valor) {
  try { localStorage.setItem(chave, String(valor)); } catch { /* sem armazenamento */ }
}
