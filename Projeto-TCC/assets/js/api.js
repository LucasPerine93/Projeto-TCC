/* Acesso às rotas REST do servidor.
   - envia o cookie de sessão (mesma origem) e um cabeçalho fixo que o backend
     pode exigir nas escritas (defesa extra contra CSRF);
   - avisa o app quando a sessão expira (HTTP 401). */

export async function api(url, { method = "GET", corpo } = {}) {
  const opcoes = {
    method,
    credentials: "same-origin",
    headers: { "X-Requested-With": "painel" },
  };
  if (corpo !== undefined) {
    opcoes.headers["Content-Type"] = "application/json";
    opcoes.body = JSON.stringify(corpo);
  }
  const resposta = await fetch(url, opcoes);
  if (resposta.status === 401 && url !== "/login" && url !== "/sessao") {
    document.dispatchEvent(new CustomEvent("sessao-expirada"));
  }
  return resposta;
}

export async function apiJson(url, opcoes) {
  const resposta = await api(url, opcoes);
  if (!resposta.ok) {
    const erro = new Error(`HTTP ${resposta.status} em ${url}`);
    erro.status = resposta.status;
    throw erro;
  }
  return resposta.json();
}
