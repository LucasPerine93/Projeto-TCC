export function LoadingState() {
  return (
    <div className="state-box" role="status">
      <div className="spinner" aria-hidden="true" />
      <h3>Carregando dados…</h3>
      <p>Consultando a API do TCC-PPE.</p>
    </div>
  );
}

export function EmptyState({ filterCount }: { filterCount: number }) {
  return (
    <div className="state-box">
      <h3>Nenhuma observação registrada</h3>
      <p>
        {filterCount > 0
          ? 'Nenhum registro corresponde aos filtros aplicados.'
          : 'O banco ainda não possui observações. Os dados aparecerão aqui após a ingestão do pipeline de visão computacional.'}
      </p>
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="state-box error" role="alert">
      <h3>Falha ao carregar os dados</h3>
      <p>{message}</p>
      <button type="button" className="btn-retry" onClick={onRetry}>
        Tentar novamente
      </button>
    </div>
  );
}
