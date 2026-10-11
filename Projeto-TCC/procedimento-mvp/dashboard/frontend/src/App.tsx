import { useEffect, useState } from 'react';
import {
  fetchCameras,
  fetchEventTypes,
  fetchObservations,
  fetchSummary,
} from './api';
import { Charts } from './components/Charts';
import { FilterBar } from './components/FilterBar';
import { KpiCard } from './components/KpiCard';
import { ObservationsTable } from './components/ObservationsTable';
import { EmptyState, ErrorState, LoadingState } from './components/States';
import type {
  Camera,
  EventType,
  Filters,
  ObservationList,
  ObservationSummary,
} from './types';

const EMPTY_FILTERS: Filters = {
  cameraCode: '',
  eventTypeCode: '',
  dateFrom: '',
  dateTo: '',
};

export default function App() {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [summary, setSummary] = useState<ObservationSummary | null>(null);
  const [observations, setObservations] = useState<ObservationList | null>(
    null,
  );
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [eventTypes, setEventTypes] = useState<EventType[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  // Catálogos dos filtros (carregam uma vez; erro deles não esconde os dados).
  useEffect(() => {
    let alive = true;
    Promise.all([fetchCameras(), fetchEventTypes()])
      .then(([c, e]) => {
        if (alive) {
          setCameras(c);
          setEventTypes(e);
        }
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  // Dados do dashboard (resumo + eventos recentes) conforme filtros.
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    Promise.all([fetchSummary(filters), fetchObservations(filters)])
      .then(([s, o]) => {
        if (alive) {
          setSummary(s);
          setObservations(o);
        }
      })
      .catch((e: unknown) => {
        if (alive) {
          setError(e instanceof Error ? e.message : String(e));
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [filters, reload]);

  const filterCount = (Object.keys(filters) as (keyof Filters)[]).filter(
    (k) => filters[k] !== '',
  ).length;

  const status = error
    ? { cls: 'err', text: 'Backend indisponível' }
    : loading
      ? { cls: '', text: 'Conectando…' }
      : { cls: 'ok', text: 'Backend conectado' };

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>TCC — Monitoramento Inteligente de EPI</h1>
          <div className="subtitle">
            Observações de visão computacional registradas no PostgreSQL
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            type="button"
            className="btn-refresh"
            onClick={() => setReload((n) => n + 1)}
            disabled={loading}
            title="Recarregar observações e resumo do backend"
          >
            Atualizar
          </button>
          <span className={`status-badge ${status.cls}`}>{status.text}</span>
        </div>
      </header>

      <FilterBar
        filters={filters}
        cameras={cameras}
        eventTypes={eventTypes}
        onChange={setFilters}
      />

      {error ? (
        <ErrorState
          message={error}
          onRetry={() => setReload((n) => n + 1)}
        />
      ) : loading && !summary ? (
        <LoadingState />
      ) : summary && observations ? (
        <>
          <section className="kpi-grid" aria-label="Indicadores">
            <KpiCard
              title="Observações registradas"
              value={String(summary.total_observations)}
              hint="registros de observação no banco"
            />
            <KpiCard
              title="Conformes"
              value={String(summary.compliant_observations)}
              accent="green"
              hint="eventos com conformidade de EPI"
            />
            <KpiCard
              title="Não conformes"
              value={String(summary.non_compliant_observations)}
              accent="red"
              hint="eventos sem conformidade de EPI"
            />
            <KpiCard
              title="Taxa de conformidade das observações"
              value={
                summary.compliance_rate === null
                  ? '—'
                  : `${(summary.compliance_rate * 100).toFixed(1)}%`
              }
              accent="amber"
              hint="sobre os registros disponíveis (não são pessoas únicas)"
            />
          </section>

          {summary.total_observations === 0 ? (
            <EmptyState filterCount={filterCount} />
          ) : (
            <Charts summary={summary} />
          )}

          <div style={{ position: 'relative' }}>
            {loading ? (
              <span
                className="status-badge"
                style={{ position: 'absolute', right: 0, top: -34 }}
              >
                Atualizando…
              </span>
            ) : null}
            <h2 className="section-title">
              Eventos recentes ({observations.total} no total com os filtros
              atuais)
            </h2>
            {observations.items.length === 0 ? (
              <EmptyState filterCount={filterCount} />
            ) : (
              <ObservationsTable items={observations.items} />
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}
