/* =========================================================================
   tela_gemeo.js — Carregamento sob demanda do Gêmeo 3D (aba "Gêmeo 3D")
   -------------------------------------------------------------------------
   Controla:
   - carga dinâmica (somente na 1ª visita à aba) dos scripts clássicos:
     Three.js local e os 3 arquivos clássicos em js/gemeo/ (fonte_dados,
     motor, interface) — a ordem importa: motor precisa do Three.js e a
     interface precisa do motor;
   - o canal de dados REAIS (mesmo WebUI do backend): registra on_connect/
     on_disconnect e o handler "telemetria_gemeo";
   - limpar ao sair da aba (pararGemeo) e avisar ao carregar com falha.
   ========================================================================= */
/* Gêmeo 3D: carrega sob demanda (só na primeira visita à aba) o Three.js local e o motor do gêmeo digital.
   Os dois arquivos em js/gemeo/ são scripts clássicos que usam os ids da própria seção. */
// ===== 1. Canal de dados reais (WebSocket WebUI do painel) =====
import { registrarTela, avisar } from "./nucleo.js";
import { ui } from "./conexao_ui.js";

/* Canal de dados reais: o mesmo socket do painel (WebUI do Arduino App Lab). O backend ainda NÃO envia "telemetria_gemeo";
   enquanto isso o gêmeo mostra "sem dados reais" (nunca inventa posições). Formato esperado: ver PLANO_EVOLUCAO.md. */
window.GemeoCanal = { conectado: false };
const canal = (sim) => { window.GemeoCanal.conectado = sim; window.GemeoPonte?.canalConectou(sim); };
if (typeof ui.on_connect === "function") ui.on_connect(() => canal(true));
if (typeof ui.on_disconnect === "function") ui.on_disconnect(() => canal(false));
ui.on_message("telemetria_gemeo", (p) => window.GemeoPonte?.receber(p));

/** Chamado ao sair: fecha a fonte real e volta o gêmeo ao estado de simulação. */
export function pararGemeo() { window.GemeoPonte?.parar(); }

// ===== 2. Carga sob demanda dos scripts clássicos =====
const ARQUIVOS = ["libs/three.min.js", "js/gemeo/fonte_dados.js", "js/gemeo/motor.js", "js/gemeo/interface.js"];
let carga = null;

function carregar(src) {
  return new Promise((ok, falhou) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = ok;
    s.onerror = () => falhou(new Error(`Não foi possível carregar ${src}`));
    document.body.append(s);
  });
}

function iniciar() {
  if (!carga) {
    // em sequência: o motor precisa do Three.js, e a interface precisa do motor
    carga = ARQUIVOS.reduce((p, src) => p.then(() => carregar(src)), Promise.resolve())
      .catch((e) => {
        carga = null;                         // permite tentar de novo ao voltar à aba
        avisar(`${e.message}. Confira se a pasta assets está completa.`, { tipo: "erro", duracao: 8000 });
      });
  }
  return carga;
}

registrarTela("gemeo", { entrar: iniciar });
