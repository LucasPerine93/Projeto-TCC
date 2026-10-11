import { useEffect, useState } from 'react';
import { fetchImagesByOccurrence, imageContentUrl } from '../api';
import type { ImageEvidence } from '../types';

type PanelState =
  | { kind: 'loading' }
  | { kind: 'ready'; items: ImageEvidence[] }
  | { kind: 'unavailable'; message: string };

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('pt-BR');
}

export function EvidencePanel({ occurrenceId }: { occurrenceId: number }) {
  const [state, setState] = useState<PanelState>({ kind: 'loading' });
  const [selected, setSelected] = useState<number | null>(null);
  const [imgBroken, setImgBroken] = useState(false);

  useEffect(() => {
    let alive = true;
    setState({ kind: 'loading' });
    setSelected(null);
    setImgBroken(false);
    fetchImagesByOccurrence(occurrenceId)
      .then((list) => {
        if (!alive) return;
        setState({ kind: 'ready', items: list.items });
        if (list.items.length > 0) setSelected(list.items[0].id);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setState({
          kind: 'unavailable',
          message: e instanceof Error ? e.message : String(e),
        });
      });
    return () => {
      alive = false;
    };
  }, [occurrenceId]);

  if (state.kind === 'loading') {
    return <span className="evidence-hint">Buscando evidências…</span>;
  }

  if (state.kind === 'unavailable') {
    return (
      <span className="evidence-hint evidence-err" role="alert">
        Evidência indisponível ({state.message})
      </span>
    );
  }

  if (state.items.length === 0) {
    return <span className="evidence-hint">Sem evidência de imagem</span>;
  }

  const current =
    state.items.find((it) => it.id === selected) ?? state.items[0];

  return (
    <div className="evidence-panel">
      {state.items.length > 1 ? (
        <div className="evidence-thumbs" role="listbox" aria-label="Evidências">
          {state.items.map((it) => (
            <button
              key={it.id}
              type="button"
              role="option"
              aria-selected={it.id === current.id}
              className={`evidence-thumb${it.id === current.id ? ' active' : ''}`}
              onClick={() => {
                setSelected(it.id);
                setImgBroken(false);
              }}
              title={`${it.file_name} — ${formatDateTime(it.created_at)}`}
            >
              Evidência #{it.id}
            </button>
          ))}
        </div>
      ) : null}
      {imgBroken ? (
        <span className="evidence-hint evidence-err" role="alert">
          Não foi possível carregar a imagem (arquivo ausente ou inacessível).
        </span>
      ) : (
        <img
          key={current.id}
          className="evidence-img"
          src={imageContentUrl(current.id)}
          alt={`Evidência da ocorrência ${current.occurrence_id}`}
          loading="lazy"
          onError={() => setImgBroken(true)}
        />
      )}
      <div className="evidence-meta">
        <span title={current.sha256}>SHA-256: {current.sha256.slice(0, 12)}…</span>
        <span>{current.mime_type}</span>
        <span>{formatDateTime(current.created_at)}</span>
      </div>
    </div>
  );
}
