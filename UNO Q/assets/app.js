window.onload = () => mostrarTela();
const ip_unoq = window.location.hostname;
const ui = new WebUI();

let senhaCorreta = false;

const botaoSenha = document.getElementById("enviar-senha");
const botaoBloquear = document.getElementById("botao-bloquear");
const caixaSenha = document.getElementById("caixa-senha");
const mensagemErro = document.getElementById("mensagem-erro");

const videoIframe = document.getElementById('video');

videoIframe.src = `http://${ip_unoq}:4912/embed`;

function mostrarTela() {
    document.getElementById("painel-bloqueio").style.display = "none";
    document.getElementById("painel-video").style.display = "none";
  
    ui.send_message("liberar", {});

    ui.on_message("permissao", (dado) => { // Toda vez que essa função é executada verifica se o servidor está liberado ou não 
      let servidorBloqueado = dado["servidor"]; // 0 servidor bloqueado | 1 servidor desbloqueado

      servidorBloqueado = parseInt(servidorBloqueado);
      
      
      if (servidorBloqueado === 0) {
          document.getElementById("servidor-bloqueado").style.display = "block";
          document.getElementById("painel-bloqueio").style.display = "none";
          document.getElementById("painel-video").style.display = "none";
    
          return;
          
        } 
        else {
          document.getElementById("servidor-bloqueado").style.display = "none";
          document.getElementById("painel-bloqueio").style.display = "block";
          document.getElementById("painel-video").style.display = "none";

          caixaSenha.focus();
          
        }
      
        if (senhaCorreta) {
            document.getElementById("servidor-bloqueado").style.display = "none";
            document.getElementById("painel-bloqueio").style.display = "none";
            document.getElementById("painel-video").style.display = "block";
    
        }
        else {
            document.getElementById("servidor-bloqueado").style.display = "none";
            document.getElementById("painel-bloqueio").style.display = "block";
            document.getElementById("painel-video").style.display = "none";

            caixaSenha.focus();
    
        }
    });
}


botaoSenha.addEventListener("click", () => {
    const senha = parseInt(caixaSenha.value);
  
    ui.send_message("senha", {senha});
    caixaSenha.value = "";
});

botaoBloquear.addEventListener("click", () => { 
  senhaCorreta = false;
  mostrarTela(); 
});

caixaSenha.addEventListener("keydown", (evento) => {
  if (evento.key === "Enter") {
    botaoSenha.click();
  }
});


ui.on_message("liberar", () => {
  senhaCorreta = true;
  mostrarTela(); 
});

ui.on_message("bloquear", () => {
    senhaCorreta = false;
    mostrarTela();
    
    mensagemErro.innerText = "Senha incorreta, tente novamente";
    setTimeout(() => {
        mensagemErro.innerText = "";
    }, 2500);
});


ui.on_message("bloquear_servidor", () => {
  senhaCorreta = false;
  mostrarTela();  
});

ui.on_message("desbloquear_servidor", () => {
  senhaCorreta = false
  mostrarTela(); 
});
