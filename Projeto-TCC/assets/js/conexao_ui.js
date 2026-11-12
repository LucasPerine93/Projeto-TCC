/* =========================================================================
   conexao_ui.js — Ponto único de acesso ao objeto WebUI (injetado pela plataforma)
   -------------------------------------------------------------------------
   Controla: a instância global ``ui`` (``window.WebUI`` do Arduino App Lab) usada
   por todos os módulos para enviar mensagens e receber telemetria. Centralizar
   aqui evita espalhar expectativas de global pelo resto do código.
   ========================================================================= */
export const ui = new WebUI();