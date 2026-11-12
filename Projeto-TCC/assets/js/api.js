/* =========================================================================
   api.js — Acesso às rotas REST do servidor (fetch padronizado)
   -------------------------------------------------------------------------
   Controla:
   - envio do cookie de sessão (mesma origem) e do cabeçalho fixo
     ``X-Requested-With: painel`` que o backend exige nas escritas
     (defesa extra contra CSRF);
   - aviso ao app (``sessao-expirada``) quando o servidor responde HTTP 401;
   - ``apiJson`` para respostas JSON com erro HTTP convertido em exceção.

   Índice de seções:
   1. fetch COM COOKIE DE SESSÃO + CABEÇALHO ANTI-CSRF
   2. RESPOSTA JSON OU ERRO HTTP COMO EXCEÇÃO
   ========================================================================= */

// ===== 1. FETCH COM COOKIE DE SESSÃO + CABEÇALHO ANTI-CSRF =====
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

/* ===== 2. RESPOSTA JSON OU ERRO HTTP COMO EXCEÇÃO ===== */
export async function apiJson(url, opcoes) {
  const resposta = await api(url, opcoes);
  if (!resposta.ok) {
    const erro = new Error(`HTTP ${resposta.status} em ${url}`);
    erro.status = resposta.status;
    throw erro;
  }
  return resposta.json();
}
