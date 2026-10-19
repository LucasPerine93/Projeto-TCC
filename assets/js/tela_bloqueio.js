import { navegarPara} from "./app.js";
import { ui } from "./conexao_ui.js";

export const campoSenha = document.getElementById("caixa-senha");
const botaoSenha = document.getElementById("enviar-senha");
const mensagemErro = document.getElementById("mensagem-erro");

botaoSenha.addEventListener("click", () => {
  const senha = parseInt(campoSenha.value);

  ui.send_message("senha", { senha });
  campoSenha.value = "";
});

campoSenha.addEventListener("keydown", (evento) => {
  if (evento.key === "Enter") {
    botaoSenha.click();
  }
});

ui.on_message("liberado", () => navegarPara("camera"));

ui.on_message("rejeitado", () => {
  navegarPara("telaBloqueio");

  mensagemErro.innerText = "Senha incorreta, tente novamente";
  setTimeout(() => {
    mensagemErro.innerText = "";
  }, 2500);
});