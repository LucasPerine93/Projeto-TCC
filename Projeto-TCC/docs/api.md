# API HTTP — Painel de EPIs

Expostas via `servidor.py` (`ui.expose_api`). Base: mesma origem do WebUI.

## Autenticação (Cookie HttpOnly + PBKDF2)

| Rota | Método | Auth | Papel |
|---|---|---|---|
| `/login` | POST | não | `{senha}` → cookie `sessao` HttpOnly + `SameSite=strict` + `ticket`; 401 senha errada; 429 após 5 falhas (bloqueio exponencial 30 s→15 min) |
| `/sessao` | GET | cookie | renova sessão (8 h) e devolve `ticket` novo |
| `/logout` | POST | cookie + `X-Requested-With: painel` | encerra sessão, limpa cookie |

Senha verificada com PBKDF2-SHA256 200 000 iterações contra
`TCC_SENHA_HASH` (variável de ambiente — nunca hardcoded).
Socket exige ticket de 30 s para escrita.

## Dados (leitura exige sessão válida)

| Rota | Método | Resposta |
|---|---|---|
| `/dashboard_dados?dias=7` | GET | período, ocorrências (total/pendentes/confirmadas/descartadas), `infracoes_por_tipo`, `pessoas_observadas`, `trilhas`, `conformidade/capacete/colete/fora_de_risco`, `serie_diaria`, `anterior` + chaves legadas |
| `/listar_ocorrencias` | GET | lista (id, timestamp, tipo, status, motivo, foto, caixas) |
| `/foto/{nome}` | GET | bytes JPEG da evidência |

## Revisão (escrita exige sessão + header `X-Requested-With: painel`)

| Rota | Método | Efeito |
|---|---|---|
| `/revisar_ocorrencia/{id}?status=&motivo=` | POST | `confirmada/descartada/pendente` — nada é apagado |
| `/excluir_ocorrencia/{id}` | POST | legado; preserva foto se ainda referenciada |

Códigos: `200` ok · `400` revisão inválida · `401` sem sessão ·
`403` origem não confiável · `404` ocorrência/foto inexistente · `429` rate-limit.
