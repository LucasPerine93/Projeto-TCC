import { mostrarTela, estado} from "./app.js";
import { carregarFotos } from "./tela_galeria.js";
import { ui } from "./conexao_ui.js";

const botaoSenha = document.getElementById("enviar-senha");
export const campoSenha = document.getElementById("caixa-senha");
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

ui.on_message("liberado", () => {
  estado.senhaCorreta = true;
  carregarFotos();
  mostrarTela();
});

ui.on_message("rejeitado", () => {
  estado.senhaCorreta = false;
  mostrarTela();

  mensagemErro.innerText = "Senha incorreta, tente novamente";
  setTimeout(() => {
    mensagemErro.innerText = "";
  }, 2500);
});