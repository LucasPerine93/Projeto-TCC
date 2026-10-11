import type { Camera, EventType, Filters } from '../types';

interface FilterBarProps {
  filters: Filters;
  cameras: Camera[];
  eventTypes: EventType[];
  onChange: (filters: Filters) => void;
}

export function FilterBar({
  filters,
  cameras,
  eventTypes,
  onChange,
}: FilterBarProps) {
  const set = (patch: Partial<Filters>) => onChange({ ...filters, ...patch });

  return (
    <div className="filters" role="group" aria-label="Filtros">
      <label>
        Período — de
        <input
          type="date"
          value={filters.dateFrom}
          onChange={(e) => set({ dateFrom: e.target.value })}
        />
      </label>
      <label>
        Período — até
        <input
          type="date"
          value={filters.dateTo}
          onChange={(e) => set({ dateTo: e.target.value })}
        />
      </label>
      <label>
        Câmera
        <select
          value={filters.cameraCode}
          onChange={(e) => set({ cameraCode: e.target.value })}
        >
          <option value="">Todas</option>
          {cameras.map((c) => (
            <option key={c.code} value={c.code}>
              {c.name} ({c.code})
            </option>
          ))}
        </select>
      </label>
      <label>
        Tipo de evento
        <select
          value={filters.eventTypeCode}
          onChange={(e) => set({ eventTypeCode: e.target.value })}
        >
          <option value="">Todos</option>
          {eventTypes.map((t) => (
            <option key={t.code} value={t.code}>
              {t.description}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className="btn-clear"
        onClick={() =>
          onChange({
            cameraCode: '',
            eventTypeCode: '',
            dateFrom: '',
            dateTo: '',
          })
        }
      >
        Limpar filtros
      </button>
    </div>
  );
}
