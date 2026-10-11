# TCC-PPE — Frontend (React + TypeScript)

Dashboard do monitoramento inteligente de EPI. Consome a API FastAPI do
`procedimento-mvp/dashboard/backend` e apresenta apenas dados reais do PostgreSQL:

- Cartões: observações registradas, conformes, não conformes e
  **taxa de conformidade das observações** (baseada nos registros
  disponíveis — não é contagem de pessoas únicas).
- Gráficos (Recharts): observações por dia, distribuição da conformidade
  e observações por tipo de evento.
- Eventos recentes com data, câmera, evento, EPI, resultado e confiança.
- Filtros: período, câmera e tipo de evento (mesmos parâmetros
  suportados pelo backend).
- Estados de carregamento, dados vazios e falha de conexão.

## Requisitos

- Node.js 18+
- Backend rodando em `http://localhost:8000` (veja `../backend/README.md`)

## Como executar (desenvolvimento)

```powershell
cd frontend
npm install
npm run dev
```

Abra <http://localhost:5173>. O backend precisa estar no ar; a origem
`http://localhost:5173` já é liberada pelo CORS do backend (padrão).

## Build de produção

```powershell
npm run build   # type-check (tsc) + bundle (vite) em dist/
npm run preview # serve dist/ em http://localhost:4173
```

## Configuração

Variável de ambiente (opcional) em `.env` na raiz do frontend:

```
VITE_API_BASE_URL=http://localhost:8000
```

> `.env` está no `.gitignore` — nunca commitado. Não há segredos no
> frontend; a API não exige autenticação no MVP.

## Estrutura

```
src/
  api.ts            # cliente HTTP (fetch + filtros + tratamento de erro)
  types.ts          # tipos espelhados nos schemas Pydantic do backend
  App.tsx           # orquestração: estado, carga dos dados, layout
  components/       # KPIs, filtros, gráficos, tabela e estados da UI
```
