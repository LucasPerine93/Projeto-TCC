# -*- coding: utf-8 -*-
"""avaliar_experimento — Protocolo de validação experimental do TCC (Seção 12
do PLANO_EVOLUCAO.md) e gerador do relatório da monografia (Seção 14,
Etapa 7).

O módulo cobre as cinco avaliações da Seção 12:

1. ``calcular_metricas_epi(contagens)`` — precisão, revocação, F1, acurácia e
   IC 95 % de Wilson por classe (capacete/colete/area_risco) + agregado micro.
2. ``avaliar_erro_posicao(pontos_medidos, calibracao=None)`` — erro euclidiano
   em metros (média, DP, mediana, p95, máximo) e faixas de distância.
3. ``avaliar_estabilidade_trilhas(eventos_trilha)`` — ID switches/min,
   fragmentação de trilha e % de associação EPI→pessoa (frames com 2+ pessoas).
4. ``avaliar_desempenho(amostras_latencia_ms, snapshots_perf)`` — latência
   mediana/média±DP/p95, FPS médio, ms/quadro e variação de
   geometrias/texturas (``GemeoPerf.snapshot()``) para checar vazamento.
5. ``gerar_relatorio_markdown(dados)`` — tabelas em Markdown (Média ± DP,
   Mediana, P95, IC 95 %) prontas para a monografia, com cabeçalho que
   informa explicitamente a origem dos dados (arquivo real ou ``--demo``).

Sem dependências externas: apenas a biblioteca padrão (``math``, ``statistics``,
``json``, ``csv``-compatível, ``argparse``, ``pathlib``).

Uso via linha de comando::

    python tools/avaliar_experimento.py --demo                    # dados sintéticos
    python tools/avaliar_experimento.py --demo --output relatorio_validacao.md
    python tools/avaliar_experimento.py --input dados_experimento.json --output relatorio_validacao.md

Formato do ``dados_experimento.json`` (todos os blocos são opcionais; seções
ausentes são renderizadas como "Sem dados — colete e adicione ao arquivo")::

    {
      "origem": {"tipo": "arquivo", "fonte": "coleta_2026-11.json"},
      "meta":   {"titulo": "...", "ambiente": "...", "data": "2026-11-11"},
      "contagens_epi": {"capacete": {"tp": 268, "fp": 31, "fn": 29, "tn": 172}, ...},
      "pontos_medidos": [{"x_real_m": 1.0, "z_real_m": 2.0, "x_est_m": 1.1, "z_est_m": 1.9}, ...],
      "calibracao":     {"H": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "frame": {"w": 720, "h": 480}},
      "eventos_trilha": [{"t": 0.0, "pessoa": "A", "track_id": 1,
                          "com_multiplas_pessoas": true, "epi_para_dono": true}, ...],
      "amostras_latencia_ms": [18.2, 22.7, ...],
      "snapshots_perf": [{"fps": 29.5, "msPorQuadro": 33.1, "geometrias": 128,
                          "texturas": 54, "chamadas": 210, "triangulos": 95000}, ...]
    }

Quando ``calibracao`` é informada (no arquivo ou passada à função), cada
medição de erro de posição deve trazer ``box_xyxy`` e a estimativa é obtida
com ``detector.projetar_pe_para_planta`` (importado sob demanda).

Sem metas inventadas (Seção 12): o relatório apresenta medições, não desvios
em relação a um objetivo. Limitações (câmera única, iluminação, perspectiva)
são declaradas no rodapé do documento gerado.
"""

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

Z_95 = 1.959963984540054  # quantil z bicaudal para IC de 95 %


# ---------------------------------------------------------------------------
# Helpers estatísticos
# ---------------------------------------------------------------------------
def _wilson(k, n, z=Z_95):
    """Intervalo de Wilson para uma proporção binomial k/n (n >= 0).

    Retorna ``(p_hat, lo, hi)``. Para ``n == 0`` retorna ``(None, None, None)``
    (proporção indefinida). ``k`` fora de ``[0, n]`` levanta ``ValueError``.
    """
    k = float(k)
    n = float(n)
    if n < 0 or k < 0 or k > n:
        raise ValueError("wilson: sucessos %r fora do intervalo [0, %r]" % (k, n))
    if n == 0:
        return None, None, None
    p = k / n
    den = 1.0 + z * z / n
    centro = (p + z * z / (2.0 * n)) / den
    termo = math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    meia = (z / den) * termo
    return p, max(0.0, centro - meia), min(1.0, centro + meia)


def _percentil(alvo_pct, valores):
    """Percentil por interpolação linear (equivalente ao PERCENTIL.INC / NumPy).

    Aceita a lista já ordenada ou não. Lista vazia -> ``None``; um elemento ->
    o próprio elemento.
    """
    dados = sorted(valores)
    if not dados:
        return None
    if len(dados) == 1:
        return float(dados[0])
    corte = (alvo_pct / 100.0) * (len(dados) - 1)
    i = int(math.floor(corte))
    fracao = corte - i
    if i + 1 < len(dados):
        return dados[i] * (1.0 - fracao) + dados[i + 1] * fracao
    return float(dados[-1])


def _desvio_padrao_amostra(valores):
    """Desvio padrão amostral (n - 1); 0.0 quando n < 2."""
    if len(valores) < 2:
        return 0.0
    return statistics.stdev(valores)


# ---------------------------------------------------------------------------
# 1) Classificação de EPIs e IC 95 % de Wilson
# ---------------------------------------------------------------------------
def _metricas_binarias(nome, c):
    try:
        tp = int(c["tp"])
        fp = int(c["fp"])
        fn = int(c["fn"])
        tn = int(c["tn"])
    except KeyError as exc:
        raise ValueError("classe %r: faltando a chave %s em contagens" % (nome, exc))
    except (TypeError, ValueError):
        raise ValueError("classe %r: tp/fp/fn/tn devem ser inteiros" % nome)
    if min(tp, fp, fn, tn) < 0:
        raise ValueError("classe %r: contagens negativas não são permitidas" % nome)

    n = tp + fp + fn + tn
    p, p_lo, p_hi = _wilson(tp, tp + fp)      # precisão é proporção binomial
    r, r_lo, r_hi = _wilson(tp, tp + fn)      # revocação idem
    a, a_lo, a_hi = _wilson(tp + tn, n)       # acurácia idem
    if p is not None and r is not None and (p + r) > 0:
        f1 = 2.0 * p * r / (p + r)
    else:
        f1 = 0.0
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "n_amostras": n,
        "suporte": tp + fn,  # ocorrência real da classe entre os anotados
        "precisao": p, "revocacao": r, "f1": f1, "acuracia": a,
        "precisao_ic95": (p_lo, p_hi),
        "revocacao_ic95": (r_lo, r_hi),
        "acuracia_ic95": (a_lo, a_hi),
    }


def calcular_metricas_epi(contagens):
    """Métricas por classe e agregado micro (TP/FP/FN/TN somados).

    ``contagens`` é ``{"capacete": {"tp": .., "fp": .., "fn": .., "tn": ..}, ...}``.

    Retorno::

        {"classes": {"capacete": {...}, ...},
         "agregado": {...}}   # micro: soma das classes

    Cada conjunto traz ``tp, fp, fn, tn, n_amostras, suporte, precisao,
    revocacao, f1, acuracia`` (floats; ``None`` quando o denominador é 0) e
    ``precisao_ic95 / revocacao_ic95 / acuracia_ic95`` como tuplas
    ``(lo, hi)`` de Wilson (ou ``(None, None)`` quando indefinidas).
    """
    if not isinstance(contagens, dict) or not contagens:
        raise ValueError("contagens deve ser um dicionário não vazio: {classe: {tp, fp, fn, tn}}")
    soma = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    classes = {}
    for nome, c in contagens.items():
        met = _metricas_binarias(str(nome), c)
        classes[str(nome)] = met
        for chave in soma:
            soma[chave] += met[chave]
    agregado = _metricas_binarias("micro", soma)
    return {"classes": classes, "agregado": agregado}


# ---------------------------------------------------------------------------
# 2) Erro de posicionamento na planta (homografia)
# ---------------------------------------------------------------------------
def _importar_detector():
    """Importa o detector real sob demanda (tools/ não depende de numpy no import)."""
    aqui = Path(__file__).resolve().parent
    python_dir = aqui.parent / "python"
    if str(python_dir) not in sys.path:
        sys.path.insert(0, str(python_dir))
    import detector  # noqa: PLC0415
    return detector


def _resumo_erros(erros):
    if not erros:
        return {"n": 0, "media_m": None, "desvio_padrao_m": None,
                "mediana_m": None, "p95_m": None, "minimo_m": None, "maximo_m": None}
    return {
        "n": len(erros),
        "media_m": statistics.fmean(erros),
        "desvio_padrao_m": _desvio_padrao_amostra(erros),
        "mediana_m": statistics.median(erros),
        "p95_m": _percentil(95.0, erros),
        "minimo_m": min(erros),
        "maximo_m": max(erros),
    }


FAIXAS_DISTANCIA = ("curta", "media", "longa")


def avaliar_erro_posicao(pontos_medidos, calibracao=None):
    """Erro euclidiano (m) entre posição estimada e medida com fita métrica.

    Cada item de ``pontos_medidos`` é::

        {"x_real_m": float, "z_real_m": float,
         "x_est_m": float, "z_est_m": float,     # modo direto
         "distancia_m": float (opcional; distância da câmera/origem),
         "box_xyxy": [x1, y1, x2, y2]}           # modo projeção (calibracao)

    Sem ``calibracao``: usa ``x_est_m``/``z_est_m`` informados.
    Com ``calibracao`` (dict do GET /calibracao ou ``{"H": ..., "frame": ...}``):
    projeta o ponto dos pés de ``box_xyxy`` com ``detector.projetar_pe_para_planta``;
    pontos para os quais a projeção falha são contabilizados em ``ignorados``.

    ``distancia_m`` por ponto, quando informada, é usada para a separação por
    faixas; caso contrário, usa-se a distância planar à origem da planta
    (``hypot(x_real_m, z_real_m)``), coerente com o enunciado da Seção 12
    ("distância da origem/câmera"). Faixas: ``curta < 5 m``,
    ``5 m <= media <= 10 m``, ``longa > 10 m``.
    """
    if not isinstance(pontos_medidos, list) or not pontos_medidos:
        raise ValueError("pontos_medidos deve ser uma lista não vazia de medições")

    erros, distancias, ignorados = [], [], 0
    detector = _importar_detector() if calibracao is not None else None

    for indice, ponto in enumerate(pontos_medidos):
        if not isinstance(ponto, dict):
            raise ValueError("medição %d: cada item deve ser um dicionário" % indice)
        try:
            x_real = float(ponto["x_real_m"])
            z_real = float(ponto["z_real_m"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("medição %d: campos x_real_m/z_real_m ausentes ou inválidos" % indice)

        if detector is not None:
            x_est, z_est, _celula = detector.projetar_pe_para_planta(ponto.get("box_xyxy"), calibracao)
            if x_est is None:
                ignorados += 1
                continue
        else:
            try:
                x_est = float(ponto["x_est_m"])
                z_est = float(ponto["z_est_m"])
            except (KeyError, TypeError, ValueError):
                raise ValueError(
                    "medição %d: informe x_est_m/z_est_m ou passe calibracao=... com box_xyxy" % indice
                )

        dist_ref = ponto.get("distancia_m")
        try:
            dist = float(dist_ref) if dist_ref is not None else math.hypot(x_real, z_real)
        except (TypeError, ValueError):
            raise ValueError("medição %d: distancia_m inválida" % indice)

        erros.append(math.hypot(x_est - x_real, z_est - z_real))
        distancias.append(dist)

    if not erros:
        raise ValueError(
            "nenhuma medição válida: todas as projeções falharam com a calibração fornecida"
        )

    resumo = _resumo_erros(erros)
    resumo["ignorados"] = ignorados
    resumo["erros_m"] = erros
    resumo["distancia_por"] = (
        "distancia_m declarada por ponto (fallback: origem da planta)"
        if any(p.get("distancia_m") is not None for p in pontos_medidos if isinstance(p, dict))
        else "origem da planta (hipotenusa do ponto real)"
    )

    faixas = {}
    for nome, dentro in (
        ("curta", lambda d: d < 5.0),
        ("media", lambda d: 5.0 <= d <= 10.0),
        ("longa", lambda d: d > 10.0),
    ):
        sub = [e for e, d in zip(erros, distancias) if dentro(d)]
        faixas[nome] = _resumo_erros(sub)
    resumo["faixas"] = faixas
    return resumo


# ---------------------------------------------------------------------------
# 3) Estabilidade de rastreamento e associação EPI→pessoa
# ---------------------------------------------------------------------------
def avaliar_estabilidade_trilhas(eventos_trilha):
    """ID switches/min, fragmentação e associação EPI→pessoa.

    Cada evento em ``eventos_trilha``::

        {"t": float (segundos),             # instante do evento na linha do tempo
         "pessoa": hashable ("A", 7...),    # identidade REAL anotada no vídeo
         "track_id": hashable,              # ID atribuído pelo rastreador
         "com_multiplas_pessoas": bool,     # frame tinha >= 2 pessoas (default False)
         "epi_para_dono": bool | None}      # EPI do frame atribuído à pessoa certa
                                            # (None quando not-applicable)

    Definições:
      * troca de ID: dentro de uma identidade real ordenada por ``t``, o
        ``track_id`` muda em relação à observação anterior;
      * fragmentação: média de trilhas contíguas por identidade real
        (1 + trocas), e ``trilhas_totais`` (soma dos segmentos);
      * associação EPI: % de ``epi_para_dono is True`` entre os frames com
        ``com_multiplas_pessoas`` que avaliaram a atribuição.
    """
    eventos = list(eventos_trilha or [])
    if not eventos:
        raise ValueError("eventos_trilha deve ser uma lista não vazia de eventos")

    normalizados = []
    for indice, e in enumerate(eventos):
        if not isinstance(e, dict):
            raise ValueError("evento %d: cada item deve ser um dicionário" % indice)
        try:
            t = float(e["t"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("evento %d: campo 't' (segundos) ausente ou inválido" % indice)
        if "pessoa" not in e or "track_id" not in e:
            raise ValueError("evento %d: campos 'pessoa' e 'track_id' são obrigatórios" % indice)
        multi = bool(e.get("com_multiplas_pessoas", False))
        epi = e.get("epi_para_dono", None)
        if epi is not None and not isinstance(epi, bool):
            raise ValueError("evento %d: epi_para_dono deve ser true/false ou ausente" % indice)
        normalizados.append({"t": t, "pessoa": e["pessoa"], "track_id": e["track_id"],
                             "multi": multi, "epi_para_dono": epi})

    n_eventos = len(normalizados)
    tempos = [e["t"] for e in normalizados]
    duracao_s = max(tempos) - min(tempos)

    por_pessoa = {}
    for e in normalizados:
        por_pessoa.setdefault(e["pessoa"], []).append(e)
    for lista in por_pessoa.values():
        lista.sort(key=lambda e: e["t"])

    id_switches = 0
    trilhas_totais = 0
    for lista in por_pessoa.values():
        segmentos = 1
        anterior = lista[0]["track_id"]
        for e in lista[1:]:
            if e["track_id"] != anterior:
                id_switches += 1
                segmentos += 1
                anterior = e["track_id"]
        trilhas_totais += segmentos

    duracao_min = duracao_s / 60.0 if duracao_s > 0 else None
    switches_por_min = (id_switches / duracao_min) if duracao_min else None
    fragmentacao = trilhas_totais / len(por_pessoa)

    frames_multi = sum(1 for e in normalizados if e["multi"])
    associacao_avaliada = sum(
        1 for e in normalizados if e["multi"] and e["epi_para_dono"] is not None
    )
    associacao_correta = sum(
        1 for e in normalizados if e["multi"] and e["epi_para_dono"] is True
    )
    associacao_pct = (100.0 * associacao_correta / associacao_avaliada) if associacao_avaliada else None

    return {
        "n_eventos": n_eventos,
        "n_identidades": len(por_pessoa),
        "duracao_s": duracao_s,
        "id_switches": id_switches,
        "id_switches_por_min": switches_por_min,
        "trilhas_totais": trilhas_totais,
        "fragmentacao_trilha": fragmentacao,
        "frames_multiplas_pessoas": frames_multi,
        "associacao_epi_avaliada": associacao_avaliada,
        "associacao_epi_correta": associacao_correta,
        "associacao_epi_correta_pct": associacao_pct,
    }


# ---------------------------------------------------------------------------
# 4) Latência, FPS e estabilidade de recursos
# ---------------------------------------------------------------------------
def _serie(snapshots, chave):
    valores = []
    for indice, s in enumerate(snapshots):
        if not isinstance(s, dict):
            raise ValueError("snapshot %d: cada item deve ser um dicionário (GemeoPerf.snapshot())" % indice)
        v = s.get(chave)
        if v is None:
            continue
        try:
            valores.append(float(v))
        except (TypeError, ValueError):
            raise ValueError("snapshot %d: campo %r não é numérico" % (indice, chave))
    return valores


def _serie_contador(valores):
    """Resumo de uma série de contadores monotônicos/estáveis (geometrias, texturas)."""
    if not valores:
        return {"inicial": None, "final": None, "delta": None,
                "minimo": None, "maximo": None,
                "crescimento_monotonico": False, "n_amostras": 0}
    contribuicoes_positivas = all(valores[i] >= valores[i - 1] for i in range(1, len(valores)))
    return {
        "inicial": valores[0],
        "final": valores[-1],
        "delta": valores[-1] - valores[0],
        "minimo": min(valores),
        "maximo": max(valores),
        "crescimento_monotonico": bool(contribuicoes_positivas and valores[-1] > valores[0]),
        "n_amostras": len(valores),
    }


def avaliar_desempenho(amostras_latencia_ms, snapshots_perf):
    """Latência (ms), FPS médio, ms/quadro e estabilidade de geometrias/texturas.

    ``amostras_latencia_ms``: lista de floats (timestamp do backend → recepção).
    ``snapshots_perf``: lista de ``GemeoPerf.snapshot()`` (chaves ``fps``,
    ``msPorQuadro``, ``geometrias``, ``texturas``, ``chamadas``, ``triangulos``
    — todas opcionais por item).
    """
    amostras = []
    for indice, v in enumerate(amostras_latencia_ms or []):
        try:
            amostras.append(float(v))
        except (TypeError, ValueError):
            raise ValueError("amostras_latencia_ms[%d] não é numérica" % indice)
    if amostras and min(amostras) < 0:
        raise ValueError("latências negativas não são permitidas")

    snapshots = list(snapshots_perf or [])
    if not amostras and not snapshots:
        raise ValueError("informe ao menos amostras_latencia_ms ou snapshots_perf")

    if amostras:
        latencia = {
            "n": len(amostras),
            "mediana_ms": statistics.median(amostras),
            "media_ms": statistics.fmean(amostras),
            "desvio_padrao_ms": _desvio_padrao_amostra(amostras),
            "p95_ms": _percentil(95.0, amostras),
            "minimo_ms": min(amostras),
            "maximo_ms": max(amostras),
        }
    else:
        latencia = None

    fps = _serie(snapshots, "fps")
    ms_por_quadro = _serie(snapshots, "msPorQuadro")
    chamadas = _serie(snapshots, "chamadas")
    triangulos = _serie(snapshots, "triangulos")

    return {
        "latencia_ms": latencia,
        "snapshots": len(snapshots),
        "fps_medio": statistics.fmean(fps) if fps else None,
        "fps_min": min(fps) if fps else None,
        "fps_max": max(fps) if fps else None,
        "ms_por_quadro_medio": statistics.fmean(ms_por_quadro) if ms_por_quadro else None,
        "chamadas_media": statistics.fmean(chamadas) if chamadas else None,
        "triangulos_media": statistics.fmean(triangulos) if triangulos else None,
        "geometrias": _serie_contador(_serie(snapshots, "geometrias")),
        "texturas": _serie_contador(_serie(snapshots, "texturas")),
    }


# ---------------------------------------------------------------------------
# 5) Formatação Markdown e gerador de relatório para a monografia
# ---------------------------------------------------------------------------
def _n(valor, casas=2):
    """Número no padrão pt-BR (vírgula decimal) ou travessão quando indefinido."""
    if valor is None:
        return "—"
    return ("%.*f" % (casas, valor)).replace(".", ",")


def _ic(ic, casas=3):
    """IC 95 % como "[lo; hi]" com vírgula decimal; indefinido -> travessão."""
    if not ic:
        return "—"
    lo, hi = ic
    if lo is None or hi is None:
        return "—"
    return "[%s; %s]" % (_n(lo, casas), _n(hi, casas))


def _media_dp(media, dp, casas=2):
    if media is None:
        return "—"
    return "%s ± %s" % (_n(media, casas), _n(dp or 0.0, casas))


def _tabela(cabecalhos, linhas_tabela):
    saida = ["| " + " | ".join(cabecalhos) + " |",
             "| " + " | ".join(["---"] * len(cabecalhos)) + " |"]
    for linha in linhas_tabela:
        saida.append("| " + " | ".join("—" if c is None else "%s" % c for c in linha) + " |")
    return "\n".join(saida)


def _nota_sem_dados(titulo_secao, secoes_sem_dados):
    secoes_sem_dados.append(titulo_secao)
    return "> **Sem dados — colete na Seção 12 e adicione ao arquivo de entrada.**"


def _secao_epi(contagens, secoes_sem_dados, erros_validacao):
    if not contagens:
        return _nota_sem_dados("1. Classificação de EPIs", secoes_sem_dados)
    try:
        res = calcular_metricas_epi(contagens)
    except ValueError as exc:
        erros_validacao.append("1. Classificação de EPIs: %s" % exc)
        return "> **Dados inválidos:** %s" % exc

    linhas = []
    for nome, met in res["classes"].items():
        linhas.append([
            "**%s**" % nome, met["n_amostras"], met["tp"], met["fp"], met["fn"], met["tn"],
            met["suporte"],
            "%s %s" % (_n(met["precisao"], 3), _ic(met["precisao_ic95"])),
            "%s %s" % (_n(met["revocacao"], 3), _ic(met["revocacao_ic95"])),
            _n(met["f1"], 3),
            "%s %s" % (_n(met["acuracia"], 3), _ic(met["acuracia_ic95"])),
        ])
    met = res["agregado"]
    linhas.append([
        "**micro (todas as classes)**", met["n_amostras"], met["tp"], met["fp"], met["fn"], met["tn"],
        met["suporte"],
        "%s %s" % (_n(met["precisao"], 3), _ic(met["precisao_ic95"])),
        "%s %s" % (_n(met["revocacao"], 3), _ic(met["revocacao_ic95"])),
        _n(met["f1"], 3),
        "%s %s" % (_n(met["acuracia"], 3), _ic(met["acuracia_ic95"])),
    ])
    tabela = _tabela(
        ["Classe", "N", "TP", "FP", "FN", "TN", "Suporte",
         "Precisão [IC 95 %]", "Revocação [IC 95 %]", "F1", "Acurácia [IC 95 %]"],
        linhas,
    )
    return (
        "%s\n\n_N por classe na coluna N; o protocolo da Seção 12 recomenda >= 300 imagens anotadas "
        "por classe. IC 95 %% pelo método de Wilson (proporções binomiais)._" % tabela
    )


def _secao_erro_posicao(pontos, calibracao, secoes_sem_dados, erros_validacao):
    if not pontos:
        return _nota_sem_dados("2. Erro de posicionamento no gêmeo", secoes_sem_dados)
    try:
        res = avaliar_erro_posicao(pontos, calibracao=calibracao)
    except ValueError as exc:
        erros_validacao.append("2. Erro de posicionamento: %s" % exc)
        return "> **Dados inválidos:** %s" % exc

    linhas = [
        ["Média ± DP", "%s m" % _media_dp(res["media_m"], res["desvio_padrao_m"], 3)],
        ["Mediana", "%s m" % _n(res["mediana_m"], 3)],
        ["p95 (interpolação linear, PERCENTIL.INC)", "%s m" % _n(res["p95_m"], 3)],
        ["Máximo", "%s m" % _n(res["maximo_m"], 3)],
        ["Mínimo", "%s m" % _n(res["minimo_m"], 3)],
        ["Pontos medidos", "%d" % res["n"]],
        ["Pontos descartados (projeção falhou)", "%d" % res["ignorados"]],
    ]
    tabela_geral = _tabela(["Estatística", "Valor"], linhas)

    linhas_faixas = []
    nomes = {"curta": "curta (< 5 m)", "media": "média (5–10 m)", "longa": "longa (> 10 m)"}
    for chave in ("curta", "media", "longa"):
        f = res["faixas"][chave]
        linhas_faixas.append([
            nomes[chave], f["n"],
            "%s ± %s" % (_n(f["media_m"], 3), _n(f["desvio_padrao_m"], 3)) if f["media_m"] is not None else "—",
            "%s" % _n(f["mediana_m"], 3) if f["mediana_m"] is not None else "—",
            "%s" % _n(f["p95_m"], 3) if f["p95_m"] is not None else "—",
            "%s" % _n(f["maximo_m"], 3) if f["maximo_m"] is not None else "—",
        ])
    tabela_faixas = _tabela(["Faixa", "N", "Média ± DP (m)", "Mediana (m)", "p95 (m)", "Máx (m)"], linhas_faixas)
    return (
        "%s\n\n%s\n\n_Referência de distância: %s._"
        % (tabela_geral, tabela_faixas, res["distancia_por"])
    )


def _secao_trilhas(eventos, secoes_sem_dados, erros_validacao):
    if not eventos:
        return _nota_sem_dados("3. Estabilidade de rastreamento", secoes_sem_dados)
    try:
        res = avaliar_estabilidade_trilhas(eventos)
    except ValueError as exc:
        erros_validacao.append("3. Estabilidade de rastreamento: %s" % exc)
        return "> **Dados inválidos:** %s" % exc

    switches_min = res["id_switches_por_min"]
    linhas = [
        ["Eventos analisados", "%d" % res["n_eventos"]],
        ["Identidades reais anotadas", "%d" % res["n_identidades"]],
        ["Duração da gravação", "%s s" % _n(res["duracao_s"], 1)],
        ["Trocas de ID (ID switches)", "%d" % res["id_switches"]],
        ["ID switches por minuto", _n(switches_min, 2) if switches_min is not None else "— (duração nula)"],
        ["Trilhas contíguas totais", "%d" % res["trilhas_totais"]],
        ["Fragmentação de trilha (segmentos/identidade)", "%s" % _n(res["fragmentacao_trilha"], 2)],
        ["Frames com >= 2 pessoas", "%d" % res["frames_multiplas_pessoas"]],
        ["Associações EPI→pessoa avaliadas", "%d" % res["associacao_epi_avaliada"]],
        ["Associação correta EPI→pessoa",
         "%d/%d (%s %%)" % (res["associacao_epi_correta"], res["associacao_epi_avaliada"],
                             _n(res["associacao_epi_correta_pct"], 1))
         if res["associacao_epi_correta_pct"] is not None else "— (nenhuma avaliada)"],
    ]
    return _tabela(["Métrica", "Valor"], linhas)


def _secao_desempenho(amostras, snapshots, secoes_sem_dados, erros_validacao):
    if not amostras and not snapshots:
        return _nota_sem_dados("4. Latência, FPS e estabilidade de recursos", secoes_sem_dados)
    try:
        res = avaliar_desempenho(amostras, snapshots)
    except ValueError as exc:
        erros_validacao.append("4. Latência e desempenho: %s" % exc)
        return "> **Dados inválidos:** %s" % exc

    partes = []
    if res["latencia_ms"]:
        lat = res["latencia_ms"]
        linhas_lat = [
            ["Amostras", "%d" % lat["n"]],
            ["Mediana", "%s ms" % _n(lat["mediana_ms"], 1)],
            ["Média ± DP", "%s ms" % _media_dp(lat["media_ms"], lat["desvio_padrao_ms"], 1)],
            ["p95", "%s ms" % _n(lat["p95_ms"], 1)],
            ["Mínimo / Máximo", "%s / %s ms" % (_n(lat["minimo_ms"], 1), _n(lat["maximo_ms"], 1))],
        ]
        partes.append(_tabela(["Latência (backend → recepção)", "Valor"], linhas_lat))
    else:
        partes.append("_Sem amostras de latência._")

    if res["snapshots"]:
        linhas_fps = [
            ["Snapshots analisados", "%d" % res["snapshots"]],
            ["FPS médio", _n(res["fps_medio"], 1)],
            ["FPS (mín / máx)", "%s / %s" % (_n(res["fps_min"], 1), _n(res["fps_max"], 1))],
            ["ms/quadro médio", _n(res["ms_por_quadro_medio"], 1)],
            ["Chamadas de render (média)", _n(res["chamadas_media"], 1)],
            ["Triângulos (média)", _n(res["triangulos_media"], 1)],
        ]
        partes.append(_tabela(["Quadro e render", "Valor"], linhas_fps))

        linhas_rec = []
        rotulos = {"geometrias": "Geometrias", "texturas": "Texturas"}
        for chave in ("geometrias", "texturas"):
            s = res[chave]
            delta = s["delta"]
            if delta is None:
                delta_txt = "—"
            elif delta > 0:
                delta_txt = "+%s" % _n(delta, 0)
            else:
                delta_txt = _n(delta, 0)  # zero ou negativo: sem sinal explícito
            linhas_rec.append([
                rotulos[chave],
                _n(s["inicial"], 0), _n(s["final"], 0),
                delta_txt,
                "sim" if s["crescimento_monotonico"] else "não",
            ])
        partes.append(_tabela(["Recurso", "Inicial", "Final", "Δ", "Crescimento monotônico?"], linhas_rec))
        partes.append(
            "_Δ = final − inicial. Crescimento monotônico sustentado de geometrias/texturas ao "
            "longo da gravação indica vazamento (Seção 10/12): neste caso, investigue antes de "
            "reportar estabilidade prolongada._"
        )
    else:
        partes.append("_Sem snapshots de desempenho (GemeoPerf.snapshot())._")
    return "\n\n".join(partes)


def _relatorio(dados):
    dados = dados if isinstance(dados, dict) else {}
    origem = dados.get("origem") or {}
    meta = dados.get("meta") or {}
    eh_demo = str(origem.get("tipo", "")).lower() == "demo"
    secoes_sem_dados = []
    erros_validacao = []

    titulo = meta.get("titulo") or "Validação Experimental do Sistema de EPIs"
    ambiente = meta.get("ambiente") or "_não informado — descreva câmera, iluminação, sujeito(s) e cena_"
    data_coleta = meta.get("data") or "_não informada_"

    linhas = ["# Relatório de Validação Experimental — %s" % titulo, ""]

    if eh_demo:
        linhas.append(
            "> ⚠️ **DADOS SINTÉTICOS (`--demo`) — NÃO CITAR NA MONOGRAFIA.** Este documento foi "
            "gerado para verificar o funcionamento do script. Os números abaixo são inventados "
            "e só servem para conferência do formato. Rode com `--input dados_experimento.json` "
            "com a coleta real da Seção 12 antes de usar em qualquer trabalho acadêmico."
        )
    else:
        fonte = origem.get("fonte") or "entrada não identificada"
        linhas.append(
            "> ✅ **Origem dos dados:** arquivo real `%s`. Confira o cabeçalho de cada seção "
            "(n e condições) antes de transcrever para a monografia." % fonte
        )
    linhas += [
        "",
        "| Item | Descrição |",
        "| --- | --- |",
        "| Ambiente | %s |" % ambiente,
        "| Data da coleta | %s |" % data_coleta,
        "",
    ]

    linhas.append("## 1. Detecção de EPIs — precisão, revocação, F1, acurácia e IC 95 % de Wilson")
    linhas.append("")
    linhas.append(_secao_epi(dados.get("contagens_epi"), secoes_sem_dados, erros_validacao))
    linhas += ["", ""]

    linhas.append("## 2. Erro de posicionamento no gêmeo (fita métrica)")
    linhas.append("")
    linhas.append(_secao_erro_posicao(dados.get("pontos_medidos"), dados.get("calibracao"),
                                      secoes_sem_dados, erros_validacao))
    linhas += ["", ""]

    linhas.append("## 3. Estabilidade de rastreamento e associação EPI→pessoa")
    linhas.append("")
    linhas.append(_secao_trilhas(dados.get("eventos_trilha"), secoes_sem_dados, erros_validacao))
    linhas += ["", ""]

    linhas.append("## 4. Latência, FPS e estabilidade de recursos")
    linhas.append("")
    linhas.append(_secao_desempenho(dados.get("amostras_latencia_ms"), dados.get("snapshots_perf"),
                                    secoes_sem_dados, erros_validacao))
    linhas += ["", ""]

    if secoes_sem_dados:
        linhas.append("## Dados não fornecidos")
        linhas.append("")
        for secao in secoes_sem_dados:
            linhas.append("- %s" % secao)
        linhas += ["", ""]

    if erros_validacao:
        linhas.append("## ⚠️ Seções com dados inválidos")
        linhas.append("")
        for erro in erros_validacao:
            linhas.append("- %s" % erro)
        linhas += ["", ""]

    linhas += [
        "## Limitações e interpretação",
        "",
        "- **Câmera única**: a posição é estimada só no plano do piso; o erro cresce com a distância",
        "  e com o ângulo de visada. Reporte sempre o p95 por faixa, não apenas a média.",
        "- **Latência**: `timestamp` do backend vs recepção assume relógios sincronizados (NTP);",
        "  sem NTP, interprete como atraso relativo entre quadros.",
        "- **ICs de Wilson** pressupõem amostras binomiais independentes (imagens não correlacionadas).",
        "  Frames de vídeo são correlacionados: cite o número real de imagens/sujeitos e, se possível,",
        "  agrupe por sessão.",
        "- **Condições de iluminação e vestimenta** afetam detectabilidade; declare-as no ambiente.",
        "- **Sem metas inventadas (Seção 12)**: este relatório reporta o que foi medido. Nenhuma",
        "  comparação com um valor-alvo é feita aqui — objetivos só com base em literatura/regulação",
        "  citada na monografia.",
        "- **Conformidade do gêmeo** é por pessoa-frame com denominador honesto; não é acurácia do",
        "  detector — reporte as duas separadamente (Tabela 1 vs Seção conformidade do painel).",
        "",
        "---",
        "",
        "*Gerado por `tools/avaliar_experimento.py` — Seções 12 e 14 (Etapa 7) do PLANO_EVOLUCAO.md. "
        "Decimais no padrão pt-BR.*",
    ]

    return "\n".join(linhas), len(erros_validacao)


def gerar_relatorio_markdown(dados):
    """Retorna o relatório completo em Markdown (string).

    O cabeçalho declara explicitamente se os dados são REAIS (arquivo informado
    em ``origem.fonte``) ou SINTÉTICOS de verificação (``origem.tipo == "demo"``).
    Seções sem dados são renderizadas como \"Sem dados\" — nunca inventadas.
    """
    return _relatorio(dados)[0]


# ---------------------------------------------------------------------------
# Dados de demonstração (sintéticos, determinísticos)
# ---------------------------------------------------------------------------
def dados_demo():
    """Dados SINTÉTICOS de verificação (determinísticos). Não usar na monografia."""
    erros_padrao = [0.12, 0.25, 0.18, 0.45, 0.62, 0.30, 0.85, 1.10, 0.74, 1.45, 1.72, 2.05]
    distancias = [1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 10.5, 11.5, 12.5, 14.0]
    pontos_medidos = []
    for i, (erro, dist) in enumerate(zip(erros_padrao, distancias)):
        sinal = 1.0 if i % 2 == 0 else -1.0
        pontos_medidos.append({
            "x_real_m": dist, "z_real_m": 0.5 * ((i * 3) % 5),
            "x_est_m": dist + sinal * erro, "z_est_m": 0.5 * ((i * 3) % 5) + sinal * erro * 0.35,
            "distancia_m": dist,
        })

    trilha = {"A": 101, "B": 102, "C": 103, "D": 104}
    switches_plan = {"A": (100, 220), "B": (150, 280)}
    eventos_trilha = []
    for passo in range(300):  # 300 passos x 6 s = 30 min de gravação simulada
        t = passo * 6.0
        for pessoa in ("A", "B", "C", "D"):
            if passo in switches_plan.get(pessoa, ()):
                trilha[pessoa] += 100
            eventos_trilha.append({
                "t": t + (ord(pessoa) - 65) * 0.4,
                "pessoa": pessoa,
                "track_id": trilha[pessoa],
                "com_multiplas_pessoas": True,
                "epi_para_dono": (passo + ord(pessoa)) % 11 != 0,
            })

    amostras_latencia_ms = [
        round(19.5 + (i * 37) % 23 + (i % 7) * 0.8, 2) for i in range(240)
    ]

    snapshots_perf = []
    for i in range(120):
        fps = 28.5 + (i % 9) * 0.35
        snapshots_perf.append({
            "fps": round(fps, 2),
            "msPorQuadro": round(1000.0 / fps, 2),
            "geometrias": 128,   # constante: sem crescimento -> sem vazamento simulado
            "texturas": 54,      # idem
            "chamadas": 240 + (i % 5) * 2,
            "triangulos": 96000 - (i % 7) * 40,
            "pixelRatio": 1.0,
        })

    return {
        "origem": {"tipo": "demo", "fonte": "--demo (dados sintéticos de verificação)"},
        "meta": {
            "titulo": "Validação do protótipo (exemplo sintético)",
            "ambiente": "Laboratório — iluminação controlada; câmera única 720×480; 2 sujeitos",
            "data": "2026-11",
        },
        "contagens_epi": {
            "capacete":   {"tp": 268, "fp": 31, "fn": 29, "tn": 172},
            "colete":     {"tp": 241, "fp": 44, "fn": 57, "tn": 158},
            "area_risco": {"tp": 180, "fp": 20, "fn": 25, "tn": 275},
        },
        "pontos_medidos": pontos_medidos,
        "eventos_trilha": eventos_trilha,
        "amostras_latencia_ms": amostras_latencia_ms,
        "snapshots_perf": snapshots_perf,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validação experimental do TCC (Seção 12) — gera o relatório da monografia.",
    )
    parser.add_argument("--demo", action="store_true",
                        help="gera o relatório com dados SINTÉTICOS de verificação (etiquetados); "
                             "não usar na monografia")
    parser.add_argument("--input", type=Path,
                        help="JSON com os dados da coleta (esquema no cabeçalho do módulo)")
    parser.add_argument("--output", type=Path,
                        help="caminho do relatório .md; omitido, imprime no stdout")
    parser.add_argument("--versao", action="store_true",
                        help="imprime informações básicas e encerra")
    args = parser.parse_args(argv)

    if args.versao:
        print("avaliar_experimento 1.0 — Seção 12/14 (Etapa 7) do PLANO_EVOLUCAO.md")
        return 0

    if args.demo and args.input:
        parser.error("--demo e --input são mutuamente exclusivos")
    if not args.demo and not args.input:
        parser.error("informe --demo ou --input dados_experimento.json")

    if args.demo:
        dados = dados_demo()
    else:
        try:
            dados = json.loads(args.input.read_text(encoding="utf-8-sig"))  # tolera BOM do PowerShell
        except (OSError, json.JSONDecodeError) as exc:
            parser.error("falha ao ler %s: %s" % (args.input, exc))
        if not isinstance(dados, dict):
            parser.error("o JSON deve conter um objeto (veja o esquema no cabeçalho do módulo)")
        dados.setdefault("origem", {"tipo": "arquivo", "fonte": str(args.input)})

    relatorio, erros = _relatorio(dados)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(relatorio, encoding="utf-8")
        print("Relatório salvo em %s" % args.output)
    else:
        # O relatório tem emoji/setas; a consola Windows (cp1252) rebentaria no print().
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            try:
                sys.stdout.buffer.write(relatorio.encode("utf-8") + b"\n")
                return 1 if erros else 0
            except Exception:
                pass
        print(relatorio)

    if erros:
        print("AVISO: %d seção(ões) com dados inválidos — veja o relatório." % erros,
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

