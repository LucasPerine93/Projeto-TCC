// Tipos espelhados nos schemas Pydantic do backend (app/schemas.py).

export interface Camera {
  id: number;
  code: string;
  name: string;
  location: string | null;
  active: boolean;
}
export interface EventType {
  id: number;
  code: string;
  description: string;
  compliant: boolean;
  epi_code: string;
  epi_name: string;
}

export interface Observation {
  id: number;
  created_at: string;
  batch_id: number;
  camera_code: string;
  camera_name: string;
  event_code: string;
  event_description: string;
  compliant: boolean;
  epi_code: string;
  epi_name: string;
  context: string;
  person_ref: number;
  event_confidence: number;
  conf_pessoa: number;
  conf_epi: number | null;
}

export interface ObservationList {
  total: number;
  items: Observation[];
}

export interface SummaryByDay {
  date: string;
  total: number;
  compliant: number;
  non_compliant: number;
}

export interface SummaryByCamera {
  camera_code: string;
  camera_name: string;
  total: number;
  compliant: number;
  non_compliant: number;
}

export interface SummaryByEventType {
  event_code: string;
  event_description: string;
  compliant: boolean;
  total: number;
}

export interface ObservationSummary {
  total_observations: number;
  compliant_observations: number;
  non_compliant_observations: number;
  // Taxa de conformidade das observações (None quando não há dados).
  compliance_rate: number | null;
  by_day: SummaryByDay[];
  by_camera: SummaryByCamera[];
  by_event_type: SummaryByEventType[];
}

// Filtros da interface (string vazia = filtro não aplicado).
export interface Filters {
  cameraCode: string;
  eventTypeCode: string;
  dateFrom: string; // YYYY-MM-DD
  dateTo: string; // YYYY-MM-DD (inclusivo na UI)
}

// Evidência de imagem (espelha ImageEvidenceOut / ImageEvidenceListOut).
// image_path NÃO é exposto pela API (bytes via /api/images/{id}/content).
export interface ImageEvidence {
  id: number;
  occurrence_id: number;
  camera_code: string;
  mime_type: string;
  file_name: string;
  sha256: string;
  created_at: string;
}

export interface ImageEvidenceList {
  total: number;
  items: ImageEvidence[];
}
