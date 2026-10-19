export function formatarCoord(cordenada) {
    /*
     * cordenada? - Verifica se a coordenada é nula ou indefinida.
     * toFixed(1) - Arredonda a coordenada para uma casa decimal.
     * ?? "--" - Se a coordenada for nula ou indefinida, retorna "--" como valor padrão.
     */
    
    const cordenadaFormatada = cordenada?.toFixed(1) ?? "--";
    return cordenadaFormatada;
}