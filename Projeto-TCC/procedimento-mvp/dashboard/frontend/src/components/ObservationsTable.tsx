import { Fragment, useState } from 'react';
import type { Observation } from '../types';
import { EvidencePanel } from './EvidencePanel';

const CONTEXT_LABEL: Record<string, string> = {
  inside: 'na área',
  outside: 'fora da área',
  no_area: 'sem área',
  indeterminate: 'indeterminado',
};

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('pt-BR');
}

export function ObservationsTable({ items }: { items: Observation[] }) {
  const [openId, setOpenId] = useState<number | null>(null);

  return (
    <div className="card">
      <h2 className="section-title">Eventos recentes</h2>
      <div className="table-wrap">
        <table className="events">
          <thead>
            <tr>
              <th>Data / hora</th>
              <th>Câmera</th>
              <th>Evento</th>
              <th>EPI</th>
              <th>Resultado</th>
              <th>Contexto</th>
              <th>Confiança</th>
              <th>Evidência</th>
            </tr>
          </thead>
          <tbody>
            {items.map((o) => (
              <Fragment key={o.id}>
                <tr>
                  <td>{formatDateTime(o.created_at)}</td>
                  <td>{o.camera_name}</td>
                  <td title={o.event_description}>
                    {o.event_code.replace(/_/g, ' ')}
                  </td>
                  <td>{o.epi_name}</td>
                  <td>
                    <span className={`badge ${o.compliant ? 'ok' : 'no'}`}>
                      {o.compliant ? 'Conforme' : 'Não conforme'}
                    </span>
                  </td>
                  <td>{CONTEXT_LABEL[o.context] ?? o.context}</td>
                  <td>{(o.event_confidence * 100).toFixed(0)}%</td>
                  <td>
                    <button
                      type="button"
                      className="btn-evidence"
                      aria-expanded={openId === o.id}
                      onClick={() => setOpenId(openId === o.id ? null : o.id)}
                    >
                      {openId === o.id ? 'Ocultar' : 'Ver imagem'}
                    </button>
                  </td>
                </tr>
                {openId === o.id ? (
                  <tr className="evidence-row">
                    <td colSpan={8}>
                      <EvidencePanel occurrenceId={o.id} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
