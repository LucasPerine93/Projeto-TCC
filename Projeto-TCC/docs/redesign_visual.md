# Redesign visual — Painel de EPIs e Gêmeo Digital

## Escopo desta etapa

Esta atualização é visual. Ela não conecta a telemetria real ao gêmeo, não altera o detector nem o esquema do SQLite.

## O que mudou

- Cabeçalho editorial próprio para a tela do Gêmeo Digital.
- Refinamento da navegação superior, marca, cartões, botões, títulos e espaçamentos do painel.
- Refinamento das barras de estado e indicadores do Gêmeo Digital.
- Abas laterais e cartões de planta, operários e eventos com hierarquia visual mais clara.
- Palco 3D com identidade azul-marinho, controles mais discretos e janela CCTV refinada.
- Ajustes de responsividade para reduzir a sobreposição entre a marca de origem e a janela CCTV em telas estreitas.
- Cores do fundo e do piso 3D harmonizadas com a identidade visual, sem adicionar geometrias, texturas externas ou bibliotecas.
- Respeito a `prefers-reduced-motion`.

## Arquivos alterados

- `assets/index.html`
- `assets/css/style.css`
- `assets/css/gemeo.css`
- `assets/js/gemeo/motor.js` (somente cores do fundo/fog/piso)

## O que foi preservado

- IDs e eventos usados pelo JavaScript.
- Navegação e controles existentes.
- Carregamento sob demanda do Three.js.
- Limite de pixel ratio e otimizações de renderização existentes.
- Detector, câmera, banco de dados, API e formato de telemetria.

## Observação

A prévia visual é uma composição de referência construída com os estilos reais e conteúdo ilustrativo. A aparência final do palco 3D depende do modelo e da cena carregados no navegador. O funcionamento e desempenho no UNO Q continuam exigindo teste no hardware real.
