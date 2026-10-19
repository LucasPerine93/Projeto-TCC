export function formatarDataHora(dataHora) {
    /*
     * cordenada? - Verifica se a coordenada é nula ou indefinida.
     * toFixed(1) - Arredonda a coordenada para uma casa decimal.
     * ?? "--" - Se a coordenada for nula ou indefinida, retorna "--" como valor padrão.
     */
    if (!dataHora) return "--";
    const dataFormatada = new Date(dataHora).toLocaleString("pt-BR");
    return dataFormatada;
}