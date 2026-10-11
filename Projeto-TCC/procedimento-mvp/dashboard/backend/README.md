# TCC-PPE — Backend

Base da API FastAPI do dashboard de monitoramento inteligente de EPI.

Etapa atual: conexão com o PostgreSQL + endpoints de consulta do MVP (somente leitura).

## Requisitos

- Python 3.11+
- PostgreSQL 17.x com o banco `tcc_ppe` já criado (`database/schema.sql` + `database/seed.sql`)

## 1. Criar o ambiente virtual (PowerShell)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## 2. Instalar as dependências

```powershell
pip install -r requirements.txt
```

## 3. Configurar o .env

```powershell
Copy-Item .env.example .env
```

Edite o `.env` e coloque a senha real do PostgreSQL:

```
DATABASE_URL=postgresql+psycopg://postgres:SUA_SENHA@localhost:5432/tcc_ppe
```

> O arquivo `.env` está no `.gitignore` e nunca deve ser commitado.

## 4. Executar o servidor

```powershell
uvicorn app.main:app --reload
```

Documentação automática:

- Swagger: http://127.0.0.1:8000/docs
- OpenAPI: http://127.0.0.1:8000/openapi.json

## 5. Executar os testes

```powershell
pytest -v
```

Os testes apenas consultam o banco (não inserem nem apagam dados).

## Endpoints

| Método | Rota                              | Descrição                              |
|--------|-----------------------------------|----------------------------------------|
| GET    | `/health`                         | Health check da aplicação              |
| GET    | `/health/db`                      | Health check real com o PostgreSQL     |
| GET    | `/api/cameras`                    | Lista as câmeras                       |
| GET    | `/api/epis`                       | Lista os EPIs                          |
| GET    | `/api/event-types`                | Lista os tipos de evento observacional |
| GET    | `/api/risk-areas`                 | Lista as áreas de risco                |
| GET    | `/api/observations`               | Lista observações (filtros: câmera, evento, conformidade, período, paginação) |
| GET    | `/api/observations/summary`       | Resumo para cartões/gráficos (contagens, taxa de conformidade, séries por dia/câmera/evento) |
| POST   | `/api/observations/ingest`        | Ingere 1 lote observacional (única escrita) |

### Observações sobre leitura

- `date_from` é inclusivo e `date_to` é **exclusivo** (menor que).
- Conformidade = `event_types.compliant` (a taxa é sobre observações registradas, não pessoas únicas).
- CORS liberado para as origens de `CORS_ORIGINS` (padrão: `http://localhost:5173`, o dev server do frontend).
