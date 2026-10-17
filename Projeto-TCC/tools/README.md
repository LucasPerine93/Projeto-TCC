# tools/ — scripts auxiliares (não sobem para a placa)

Esta pasta guarda utilidades de desenvolvimento. O servidor de preview
**não é versionado**: ele mora em `C:\Users\Usuario\Desktop\TCC\_preview_tcc\preview_server.py`
(e fora do Git de propósito, pois semeia banco fake + injeta hash de teste).

## Preview local do painel (Windows)

```powershell
cd C:\Users\Usuario\Desktop\TCC\_preview_tcc
python preview_server.py
# abre http://localhost:8017/  (senha de teste: admin123)
```

O preview:
- aponta `PYTHON_DIR` para `Projeto-TCC/python` e `ASSETS` para
  `Projeto-TCC/assets` (verificado: caminhos continuam corretos);
- importa as funções REAIS de `banco.py`/`seguranca.py` (com stubs só para
  `arduino.*`/`fastapi`, ausentes no Windows);
- faz monkey-patch de `banco.CAMINHO_BANCO`/`banco.PASTA_FOTOS` para um
  SQLite temporário em `_preview_tcc/` — os aliases mantidos no `banco.py`
  (`CAMINHO_BANCO = config.CAMINHO_BANCO`) garantem que isso continua
  funcionando após a criação de `python/config.py`;
- serve os assets REAIS nos mesmos endpoints do UNO Q (`/`, `/app.js`,
  `/dashboard_dados`, `/listar_ocorrencias`, `/foto/{nome}`).
