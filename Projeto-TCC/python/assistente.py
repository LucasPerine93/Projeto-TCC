"""Assistente contextual somente-leitura (Secao 11 / Etapa 8 do Plano de Evolucao).

Responde perguntas OLHANDO SOMENTE os helpers ja existentes de ``banco.py``:

- ``banco.calcular_dados_dashboard`` (periodo + conformidade pessoa-frame);
- ``banco.dados_ocorrencias``        (base bruta, se necessario);
- ``banco.obter_mapa_calor``         (exposicao agregada por celula).

Nenhuma escrita, nenhuma alteracao de regra de seguranca, area de risco ou de
equipamento. O modelo externo (LLM) e OPCIONAL e so entra se a variavel de
ambiente ``ASSISTENTE_LLM_URL`` estiver definida; mesmo assim o payload
enviado e apenas a pergunta + um resumo agregado de numeros (sem imagens,
sem dados pessoais identificaveis). Qualquer falha do proxy cai de volta no
motor local deterministico (100% offline).
"""
import json
import os
import unicodedata
import urllib.request

import banco
import config

META_CONFORMIDADE = float(config.META_CONFORMIDADE)
JANELA_DIAS = 7
MAX_PERGUNTA = 500

# Conversao celula -> coordenadas do mundo 3D (grade 80x60 de 0,5 m sobre um
# mundo 40 m x 30 m centrado na origem — mesma convencao das Secoes 3 e 5).
COLS_GRADE, LINHAS_GRADE = 80, 60
CELULA_M = 0.5
MUNDO_LARGURA, MUNDO_PROFUNDIDADE = 40.0, 30.0

ASSISTENTE_LLM_URL = os.environ.get("ASSISTENTE_LLM_URL", "").strip()


def _sem_acento(texto):
    normalizado = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in normalizado if unicodedata.category(c) != "Mn").lower()


def idx_para_coords(celula_idx):
    """Converte o indice de uma celula (0..4799) para o centro (x_m, z_m)."""
    idx = int(celula_idx)
    col, linha = idx % COLS_GRADE, (idx // COLS_GRADE) % LINHAS_GRADE
    x_m = (col + 0.5) * CELULA_M - MUNDO_LARGURA / 2
    z_m = (linha + 0.5) * CELULA_M - MUNDO_PROFUNDIDADE / 2
    return x_m, z_m


def _pct(valor, casas=1):
    if valor is None:
        return "—"
    return str(round(float(valor), casas)).replace(".", ",")


def _seg(valor):
    if valor is None:
        return "0"
    return str(int(round(float(valor))))


def _coletar_fatos():
    """Junta num dict serializavel APENAS dados agregados de leitura do banco."""
    try:
        painel = banco.calcular_dados_dashboard(JANELA_DIAS)
    except Exception:
        painel = {}
    try:
        mapa = banco.obter_mapa_calor()
    except Exception:
        mapa = []

    ocorrencias = (painel.get("ocorrencias") if isinstance(painel, dict) else None) or {
        "total": 0, "pendentes": 0, "confirmadas": 0, "descartadas": 0,
    }
    por_tipo = (painel.get("infracoes_por_tipo") if isinstance(painel, dict) else None) or {}
    anterior = (painel.get("anterior") if isinstance(painel, dict) else None) or {}

    fatos = {
        "periodo_dias": JANELA_DIAS,
        "meta_conformidade": META_CONFORMIDADE,
        "ocorrencias": {
            "total": int(ocorrencias.get("total") or 0),
            "pendentes": int(ocorrencias.get("pendentes") or 0),
            "confirmadas": int(ocorrencias.get("confirmadas") or 0),
            "descartadas": int(ocorrencias.get("descartadas") or 0),
        },
        "infracoes_por_tipo": {k: int(v) for k, v in por_tipo.items()},
        "pessoas_observadas": painel.get("pessoas_observadas") if isinstance(painel, dict) else None,
        "trilhas": painel.get("trilhas") if isinstance(painel, dict) else None,
        "conformidade_atual": painel.get("conformidade") if isinstance(painel, dict) else None,
        "capacete": painel.get("capacete") if isinstance(painel, dict) else None,
        "colete": painel.get("colete") if isinstance(painel, dict) else None,
        "fora_de_risco": painel.get("fora_de_risco") if isinstance(painel, dict) else None,
        "conformidade_anterior": anterior.get("conformidade"),
        "pessoas_anterior": anterior.get("pessoas_observadas"),
        "zona_critica": None,
    }

    if mapa:
        campeao = max(
            mapa,
            key=lambda c: (
                float(c.get("segundos_infracao") or 0),
                int(c.get("total_eventos") or 0),
            ),
        )
        x_m, z_m = idx_para_coords(campeao.get("celula_idx", 0) or 0)
        fatos["zona_critica"] = {
            "celula_idx": int(campeao.get("celula_idx", 0) or 0),
            "x_m": round(x_m, 1),
            "z_m": round(z_m, 1),
            "segundos_infracao": float(campeao.get("segundos_infracao") or 0),
            "segundos_presenca": float(campeao.get("segundos_presenca") or 0),
            "taxa_infracao": float(campeao.get("taxa_infracao") or 0),
            "total_eventos": int(campeao.get("total_eventos") or 0),
        }

    return fatos


def _acao_zona(fatos):
    zona = fatos.get("zona_critica")
    if not zona:
        return None
    return {"tipo": "focar_gemeo", "x_m": zona["x_m"], "z_m": zona["z_m"]}


def _top_tipo(por_tipo, total):
    if not por_tipo or not total:
        return None
    top_tipo, top_n = max(por_tipo.items(), key=lambda kv: kv[1])
    return top_tipo, int(top_n), _pct(100 * float(top_n) / float(total), 1)


def _resposta_ocorrencias(fatos):
    occ = fatos["ocorrencias"]
    por_tipo = fatos["infracoes_por_tipo"]
    dias = fatos["periodo_dias"]
    total = occ["total"]

    if not total:
        return (
            f"Ainda não há ocorrências válidas nos últimos {dias} dias. "
            "O registro começa quando o detector identifica ausência de EPI "
            "ou invasão da área de risco; revise a calibração e a flag de área, se esperava dados."
        ), None

    capacete = por_tipo.get("Sem capacete", 0) + por_tipo.get("Sem capacete e colete", 0)
    colete = por_tipo.get("Sem colete", 0) + por_tipo.get("Sem capacete e colete", 0)
    risco = por_tipo.get("Invasao de area de risco", 0)

    top = _top_tipo(por_tipo, total)
    top_txt = f' O tipo mais frequente é "{top[0]}" ({top[1]} ocorrência(s), {top[2]}% do total).' if top else ""

    texto = (
        f"Nos últimos {dias} dias foram registradas {total} ocorrência(s) válida(s): "
        f"{occ['pendentes']} pendente(s) de revisão, {occ['confirmadas']} confirmada(s) "
        f"e {occ['descartadas']} descartada(s) como falso positivo. "
        f"Por tipo — Sem capacete: {por_tipo.get('Sem capacete', 0)}; "
        f"Sem colete: {por_tipo.get('Sem colete', 0)}; "
        f"Sem capacete e colete: {por_tipo.get('Sem capacete e colete', 0)}; "
        f"invasão de área de risco: {risco}. "
        f"Agrupando por EPI: capacete com ausência em {capacete} ocorrência(s); "
        f"colete com ausência em {colete}.{top_txt}"
    )
    return texto, None


def _resposta_zona(fatos):
    zona = fatos.get("zona_critica")
    dias = fatos["periodo_dias"]

    if not zona:
        return (
            f"Ainda não há dados de exposição por célula (últimos {dias} dias). "
            "O mapa de calor se preenche durante a operação com pessoas detectadas na zona; "
            "confira se a calibração da câmera está ativa."
        ), None

    taxa_pct = _pct(100 * zona["taxa_infracao"], 1)
    texto = (
        f"A zona mais crítica é a célula #{zona['celula_idx']} "
        f"(x ≈ {str(zona['x_m']).replace('.', ',')} m, z ≈ {str(zona['z_m']).replace('.', ',')} m): "
        f"{_seg(zona['segundos_infracao'])} s de exposição com infração sobre "
        f"{_seg(zona['segundos_presenca'])} s de presença total (taxa de infração {taxa_pct}% "
        f"— {zona['total_eventos']} evento(s)). "
        "Ação sugerida: revisar a área e reforçar a sinalização; você pode ver a região no Gêmeo 3D com o mapa de calor ligado."
    )
    return texto, _acao_zona(fatos)


def _resposta_conformidade(fatos):
    dias = fatos["periodo_dias"]
    atual = fatos["conformidade_atual"]
    anterior = fatos["conformidade_anterior"]

    if atual is None:
        return (
            f"Ainda não há amostragem pessoa-frame no período de {dias} dias; "
            "sem ela, não dá para medir a taxa Pessoa-Frame. Deixe o sistema observar o piso "
            "por algum tempo e pergunte de novo."
        ), None

    falta = max(0.0, META_CONFORMIDADE - float(atual))
    texto = (
        f"Nos últimos {dias} dias a conformidade Pessoa-Frame está em {_pct(atual)}% "
        f"(meta de {META_CONFORMIDADE:g}%"
        + (f" — faltam {_pct(falta)} p.p." if falta > 0 else " — meta atingida")
        + ")"
    )

    pessoas = fatos.get("pessoas_observadas")
    if pessoas:
        texto += f" sobre {int(pessoas)} pessoa(s) observada(s)."
    else:
        texto += "."

    if anterior is not None:
        delta = float(atual) - float(anterior)
        tendencia = "alta" if delta > 0 else ("baixa" if delta < 0 else "estável")
        delta_txt = str(round(delta, 1)).replace(".", ",")
        texto += (
            f" No período anterior era {_pct(anterior)}% "
            f"(variação de {delta_txt} p.p., em {tendencia})."
        )
    return texto, None


def _resposta_resumo(fatos):
    occ = fatos["ocorrencias"]
    por_tipo = fatos["infracoes_por_tipo"]
    dias = fatos["periodo_dias"]

    partes = [f"Resumo dos últimos {dias} dias."]

    if occ["total"]:
        partes.append(
            f"{occ['total']} ocorrência(s) válida(s): {occ['pendentes']} pendente(s) de revisão, "
            f"{occ['confirmadas']} confirmada(s) e {occ['descartadas']} descartada(s)."
        )
        top = _top_tipo(por_tipo, occ["total"])
        if top:
            partes.append(f'Motivo mais frequente: "{top[0]}" ({top[1]}x, {top[2]}%).')
    else:
        partes.append("Nenhuma ocorrência registrada no período.")

    atual = fatos["conformidade_atual"]
    if atual is not None:
        falta = max(0.0, META_CONFORMIDADE - float(atual))
        if falta > 0:
            partes.append(
                f"Conformidade Pessoa-Frame em {_pct(atual)}%, abaixo da meta de {META_CONFORMIDADE:g}% "
                f"(faltam {_pct(falta)} p.p.)."
            )
        else:
            partes.append(f"Conformidade Pessoa-Frame em {_pct(atual)}%, acima da meta de {META_CONFORMIDADE:g}%.")
    else:
        partes.append("Sem amostragem Pessoa-Frame suficiente no período.")

    zona = fatos.get("zona_critica")
    if zona:
        partes.append(
            f"Zona mais crítica: célula #{zona['celula_idx']} "
            f"(x ≈ {str(zona['x_m']).replace('.', ',')} m, z ≈ {str(zona['z_m']).replace('.', ',')} m) "
            f"com {_seg(zona['segundos_infracao'])} s de infração acumulada."
        )

    if occ["pendentes"]:
        partes.append(f"Atenção: {occ['pendentes']} pendente(s) aguardando revisão humana no painel de Ocorrências.")

    return " ".join(partes), None


def _categoria(pergunta):
    p = _sem_acento(pergunta)

    def tem(*termos):
        return any(termo in p for termo in termos)

    if tem("zona", "calor", "critic", "onde", "local", "area", "celula", "regiao", "mapa", "evento"):
        return "zona"
    if tem("conformidade", "meta", "compar", "anterior", "percentual", "taxa de", "melhorou", "piorou"):
        return "conformidade"
    if tem("ocorrencia", "tipo", "frequente", "epi", "capacete", "colete", "infracao", "comum", "motivo"):
        return "ocorrencias"
    # pergunta ampla / resumo / panorama (ou qualquer outra coisa)
    return "resumo"


def _tentar_proxy(pergunta, fatos):
    """Usa o LLM externo SOMENTE se ASSISTENTE_LLM_URL estiver definida."""
    url = ASSISTENTE_LLM_URL
    if not url:
        return None
    try:
        payload = json.dumps({
            "papel": "Assistente somente-leitura do painel de EPIs de um canteiro. Responda em pt-BR, citando apenas os fatos enviados. Não invente números.",
            "pergunta": pergunta,
            "fatos": fatos,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            resposta = json.loads(resp.read().decode("utf-8"))
        texto = resposta.get("resposta") or resposta.get("texto") or resposta.get("answer")
        if isinstance(texto, str) and texto.strip():
            return texto.strip()
    except Exception:
        return None
    return None


def responder(pergunta):
    """Responde a pergunta com dados reais (nunca escreve no banco)."""
    if not isinstance(pergunta, str):
        pergunta = ""
    pergunta = pergunta.strip()[:MAX_PERGUNTA]
    if not pergunta:
        return {"resposta": "Pergunta vazia.", "fatos": {}, "acao": None}

    fatos = _coletar_fatos()
    categoria = _categoria(pergunta)
    acao = None

    texto = _tentar_proxy(pergunta, fatos)
    if texto is None:
        if categoria == "ocorrencias":
            texto, acao = _resposta_ocorrencias(fatos)
        elif categoria == "zona":
            texto, acao = _resposta_zona(fatos)
        elif categoria == "conformidade":
            texto, acao = _resposta_conformidade(fatos)
        else:
            texto, acao = _resposta_resumo(fatos)
    elif categoria == "zona":
        acao = _acao_zona(fatos)

    # Auditoria mínima: registra a pergunta e um trecho curto da resposta.
    try:
        print(f"[AUDITORIA][assistente] pergunta={pergunta!r} resposta={texto[:160]!r}")
    except Exception:
        pass

    return {"resposta": texto, "fatos": fatos, "acao": acao}
