# Metodologia — taxa de conformidade (denominador pessoa-frame)

## Problema

Contar só infrações (numerador) não mede conformidade: 2 infrações em 10
pessoas observadas (80 %) é muito diferente de 2 em 1000 (99,8 %).

## Unidade: pessoa-frame

Cada pessoa vista em um frame conta 1 observação (`amostragem.registrar`
roda **depois** de associar trilhas e definir `tem_*/risco_detectado`,
inclusive para os conformes). A razão independe do FPS.

## Cálculo

```
conformidade = 100 × conformes / pessoas_observadas
conforme   = tem_capacete AND tem_colete AND NOT risco_detectado
```

Taxas irmãs: `capacete = com_capacete/pessoas`, `colete = com_colete/pessoas`,
`fora_de_risco = 1 − em_risco/risco_ativo` (nulo sem área definida).

## Agregação

- Contadores em memória por minuto (`_baldes`), descarregados ao SQLite
  (`amostras_minuto`) a cada `INTERVALO_GRAVACAO = 30 s` — 10 fps nunca viram
  10 escritas/s (poupa o pendrive).
- Sem dados no período → `None` (painel mostra "—", nunca 0 % inventado).
- Série diária agrupa por dia; dia sem dados = lacuna no gráfico, não zero.

## Meta

`META_CONFORMIDADE = 95` (`python/config.py`, espelho em `tela_painel.js`):
`≥ 95 %` dentro da meta · `85–95 %` atenção · `< 85 %` crítico.

## Exemplo validado em teste

3 pessoas × 20 frames (1 completa, 1 sem capacete, 1 sem colete) →
`pessoas_observadas = 60`, `conformidade = 33,3 %`
(`tests/test_painel.py::test_conformidade_via_detector`).
