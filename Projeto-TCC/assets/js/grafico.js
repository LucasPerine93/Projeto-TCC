/* Gráfico de linha em SVG puro (sem biblioteca).
   pontos: [{ rotulo, valor }]; valor === null = dia sem dados (lacuna, nunca 0%). */
const NS = "http://www.w3.org/2000/svg";

function no(nome, atributos = {}, texto) {
  const e = document.createElementNS(NS, nome);
  for (const [k, v] of Object.entries(atributos)) e.setAttribute(k, String(v));
  if (texto !== undefined) e.textContent = texto;
  return e;
}

export function desenharLinha(svg, pontos, { meta = null } = {}) {
  const largura = Math.max(300, Math.round(svg.getBoundingClientRect().width));
  const altura = 200;
  const E = 40, D = 18, T = 14, B = 28;
  svg.setAttribute("viewBox", `0 0 ${largura} ${altura}`);
  svg.replaceChildren();

  const valores = pontos.map((p) => p.valor).filter((v) => v !== null);
  const minimo = Math.min(...valores, meta ?? 100);
  const y0 = Math.max(0, Math.floor((minimo - 5) / 10) * 10);
  const y1 = 100;
  const passo = (y1 - y0) <= 20 ? 5 : 10;
  const x = (i) => (pontos.length === 1 ? (E + largura - D) / 2 : E + (i * (largura - E - D)) / (pontos.length - 1));
  const y = (v) => T + ((y1 - v) * (altura - T - B)) / (y1 - y0);

  for (let v = y0; v <= y1; v += passo) {
    svg.append(no("line", { x1: E, x2: largura - D, y1: y(v), y2: y(v), stroke: "var(--borda)" }));
    svg.append(no("text", { x: E - 6, y: y(v) + 4, "text-anchor": "end" }, `${v}%`));
  }
  if (meta !== null) {
    svg.append(no("line", { x1: E, x2: largura - D, y1: y(meta), y2: y(meta), stroke: "var(--texto)", "stroke-dasharray": "4 4" }));
    svg.append(no("text", { x: largura - D, y: y(meta) - 5, "text-anchor": "end" }, `meta ${meta}%`));
  }

  // Segmentos contínuos: um dia sem dados interrompe a linha.
  const segmentos = [];
  let atual = [];
  pontos.forEach((p, i) => {
    if (p.valor === null) { if (atual.length) segmentos.push(atual); atual = []; }
    else atual.push([x(i), y(p.valor)]);
  });
  if (atual.length) segmentos.push(atual);
  segmentos.forEach((seg) => {
    if (seg.length > 1) {
      svg.append(no("polyline", {
        points: seg.map((q) => q.join(",")).join(" "), fill: "none", stroke: "var(--marca)",
        "stroke-width": 3, "stroke-linejoin": "round", pathLength: 1, class: "linha-anim",
      }));
    }
  });

  const salto = Math.max(1, Math.ceil(pontos.length / Math.max(2, Math.floor((largura - E - D) / 64))));
  pontos.forEach((p, i) => {
    if (i % salto === 0 || i === pontos.length - 1) {
      svg.append(no("text", { x: x(i), y: altura - 8, "text-anchor": i === pontos.length - 1 && pontos.length > 1 ? "end" : i === 0 ? "start" : "middle" }, p.rotulo));
    }
    if (p.valor !== null) {
      const c = no("circle", { cx: x(i), cy: y(p.valor), r: pontos.length > 14 ? 3 : 5, fill: "var(--superficie)", stroke: "var(--marca)", "stroke-width": 3 });
      c.append(no("title", {}, `${p.rotulo}: ${String(p.valor).replace(".", ",")}%`));
      svg.append(c);
    } else if (pontos.length <= 10) {
      svg.append(no("text", { x: x(i), y: altura - B - 6, "text-anchor": i === 0 ? "start" : "middle", opacity: 0.7 }, "sem dados"));
    }
  });

  const comDados = valores.length;
  svg.setAttribute("aria-label", comDados
    ? `Conformidade diária: de ${Math.min(...valores).toString().replace(".", ",")}% a ${Math.max(...valores).toString().replace(".", ",")}%, em ${comDados} dia(s) com dados`
    : "Conformidade diária: sem dados no período");
}

/** Rosca em SVG puro. itens: [{ rotulo, valor, cor }]. A animação de preenchimento é
 *  feita por transição CSS de stroke-dasharray (acionada depois do primeiro quadro). */
export function desenharRosca(svg, itens, { centro = "", legendaCentro = "" } = {}) {
  svg.replaceChildren();
  svg.setAttribute("viewBox", "0 0 42 42");
  const total = itens.reduce((s, i) => s + i.valor, 0);
  svg.append(no("circle", { cx: 21, cy: 21, r: 15.915, fill: "none", stroke: "var(--superficie-2)", "stroke-width": 6 }));
  if (total > 0) {
    let acumulado = 0;
    const folga = itens.filter((i) => i.valor > 0).length > 1 ? 0.8 : 0;
    const arcos = [];
    itens.forEach((item) => {
      if (item.valor <= 0) return;
      const pct = (item.valor / total) * 100;
      const arco = no("circle", {
        cx: 21, cy: 21, r: 15.915, fill: "none", stroke: item.cor, "stroke-width": 6,
        "stroke-dasharray": "0 100", "stroke-dashoffset": 25 - acumulado, class: "rosca-arco",
      });
      arco.append(no("title", {}, `${item.rotulo}: ${item.valor} (${pct.toFixed(0)}%)`));
      svg.append(arco);
      arcos.push([arco, Math.max(0, pct - folga)]);
      acumulado += pct;
    });
    requestAnimationFrame(() => requestAnimationFrame(() => {
      arcos.forEach(([arco, len]) => arco.setAttribute("stroke-dasharray", `${len} ${100 - len}`));
    }));
  }
  svg.append(no("text", { x: 21, y: 21.5, "text-anchor": "middle", class: "rosca-numero" }, String(centro)));
  svg.append(no("text", { x: 21, y: 26.5, "text-anchor": "middle", class: "rosca-legenda" }, legendaCentro));
  svg.setAttribute("aria-label", total > 0
    ? `Distribuição das infrações: ${itens.filter((i) => i.valor > 0).map((i) => `${i.rotulo} ${i.valor}`).join(", ")}`
    : "Sem infrações no período");
}
