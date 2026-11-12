@echo off
rem ============================================================
rem  Iniciar_Demo_TCC.bat - LANCADOR DE 1 CLIQUE
rem ------------------------------------------------------------
rem  Abre o painel completo do TCC no navegador, sem terminal
rem  aberto a mao e sem digitar comando:
rem    1) semeia o banco SQLite de demonstracao (tools\.demo)
rem    2) sobe o WebSocket de telemetria (ws_teste_gemeo.py, :8000)
rem    3) sobe o painel real (python\servidor.py, :8765)
rem    4) sobe a camera simulada (:4912/embed) para a tela "Ao vivo"
rem    5) abre o navegador e imprime login/senha no console
rem
rem  Login: admin / admin123
rem  Encerrar: Ctrl+C nesta janela (ou feche a janela).
rem  Fica aqui no repositorio: Projeto-TCC\Iniciar_Demo_TCC.bat
rem ============================================================
setlocal
set "PROJETO=%~dp0"
cd /d "%PROJETO%"

if not exist "python\servidor.py" (
  echo.
  echo [ERRO] Estrutura do Projeto-TCC nao encontrada em:
  echo         "%PROJETO%"
  echo        Copie este .bat para a pasta Projeto-TCC do repositorio.
  echo.
  pause
  exit /b 1
)

if not exist "tools\iniciar_demo.py" (
  echo.
  echo [ERRO] tools\iniciar_demo.py nao encontrado em "%PROJETO%"
  echo        Atualize o repositorio com "git pull" e tente de novo.
  echo.
  pause
  exit /b 1
)

echo.
echo ==============================================================
echo   INICIANDO O PAINEL DO TCC - MODO DEMONSTRACAO
echo ==============================================================
echo.

python tools\iniciar_demo.py
set "CODIGO=%ERRORLEVEL%"

if not "%CODIGO%"=="0" (
  echo.
  echo [ERRO] O lancador terminou com codigo %CODIGO%.
  echo        A janela fica aberta para leitura. Pressione qualquer
  echo        tecla para fechar.
  pause
)
exit /b %CODIGO%