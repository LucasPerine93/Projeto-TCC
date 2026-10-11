import type {
  Camera,
  EventType,
  Filters,
  ImageEvidenceList,
  ObservationList,
  ObservationSummary,
} from './types';

const RAW_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  'http://localhost:8000';
const BASE = RAW_BASE.replace(/\/+$/, '');

/** Data inclusiva da UI vira limite exclusivo no backend (date_to < x). */
function nextDay(isoDate: string): string {
  const d = new Date(`${isoDate}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

function buildParams(filters: Filters): URLSearchParams {
  const p = new URLSearchParams();
  if (filters.cameraCode) p.set('camera_code', filters.cameraCode);
  if (filters.eventTypeCode) p.set('event_type_code', filters.eventTypeCode);
  if (filters.dateFrom) p.set('date_from', `${filters.dateFrom}T00:00:00`);
  if (filters.dateTo) p.set('date_to', `${nextDay(filters.dateTo)}T00:00:00`);
  return p;
}

async function getJson<T>(path: string, params?: URLSearchParams): Promise<T> {
  const qs = params ? params.toString() : '';
  const url = BASE + path + (qs ? `?${qs}` : '');

  let res: Response;
  try {
    res = await fetch(url, { signal: AbortSignal.timeout(15000) });
  } catch {
    throw new Error(
      `Não foi possível conectar ao backend (${BASE}). ` +
        'Verifique se o uvicorn está em execução.',
    );
  }

  if (!res.ok) {
    let detail = '';
    try {
      const body = (await res.json()) as { detail?: string };
      detail = body.detail ?? '';
    } catch {
      // corpo não era JSON — ignora
    }
    throw new Error(`Erro na API (${res.status}) em ${path}. ${detail}`.trim());
  }

  return (await res.json()) as T;
}

export function fetchCameras(): Promise<Camera[]> {
  return getJson<Camera[]>('/api/cameras');
}

export function fetchEventTypes(): Promise<EventType[]> {
  return getJson<EventType[]>('/api/event-types');
}

export function fetchSummary(filters: Filters): Promise<ObservationSummary> {
  return getJson<ObservationSummary>(
    '/api/observations/summary',
    buildParams(filters),
  );
}

export function fetchObservations(
  filters: Filters,
  limit = 15,
): Promise<ObservationList> {
  const p = buildParams(filters);
  p.set('limit', String(limit));
  return getJson<ObservationList>('/api/observations', p);
}

/** Lista as evidências vinculadas a uma ocorrência (observations.id). */
export function fetchImagesByOccurrence(
  occurrenceId: number,
): Promise<ImageEvidenceList> {
  if (!Number.isInteger(occurrenceId) || occurrenceId <= 0) {
    return Promise.reject(new Error('occurrence_id inválido.'));
  }
  return getJson<ImageEvidenceList>(
    `/api/images/by-occurrence/${occurrenceId}`,
  );
}

/** URL do conteúdo binário da evidência (GET /api/images/{id}/content). */
export function imageContentUrl(imageId: number): string {
  return `${BASE}/api/images/${imageId}/content`;
}

export { BASE as API_BASE };
