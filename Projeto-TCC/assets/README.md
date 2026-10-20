# Favicon ampliado — Painel de EPIs

Este pacote troca o ícone anterior por uma versão mais simples e de maior contraste, com o escudo ocupando quase todo o canvas e menos detalhes que desaparecem a 16 px.

## Instalação
1. Faça commit ou backup das alterações atuais.
2. Extraia/mescle a pasta `Projeto-TCC/assets/` no projeto existente. Não substitua a pasta inteira do projeto.
3. Na raiz do repositório, execute `python Projeto-TCC/assets/install_favicons.py`.
4. Para um preview separado, use `python Projeto-TCC/assets/install_favicons.py --index "CAMINHO\index.html"`.
5. O script cria um backup do HTML e para com aviso se encontrar outros links de favicon não gerados por ele.
6. Use Ctrl+F5 e, se ainda aparecer o antigo, feche e reabra a aba. Favicons ficam em cache.

Os arquivos são copiados para a mesma pasta do HTML alvo; isso combina com a estrutura atual do repositório, em que o `index.html` fica dentro de `assets/`.
