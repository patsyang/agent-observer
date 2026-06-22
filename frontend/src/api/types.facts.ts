export type FactQuality = 'high' | 'low' | 'unknown';
export type TimeWindow = '1h' | '24h' | '7d' | 'all';

export interface ObservedFact {
  fact_id: string;
  source_event_id?: string;
  fact_type: string;
  category: string;
  quality: FactQuality;
  severity: string;
  summary: string;
  occurred_at: string;
  ingested_at?: string;
  source: string;
  promoted_to_signal: boolean;
  source_event_type?: string;
  source_label?: string;
  content_preview?: string;
  raw_available?: boolean;
  raw_status?: string;
}

export interface FactsResponse {
  facts: ObservedFact[];
  total?: number;
  limit?: number;
  offset?: number;
  page?: number;
  page_size?: number;
  has_more?: boolean;
  time_basis?: 'occurred' | 'ingested';
}

export interface EvidenceProjection {
  projection_id: string;
  fact_id: string;
  category: string;
  span: string;
  raw_hash: string;
  projection_json: Record<string, unknown>;
  upload_raw: boolean;
  raw_content: string | null;
}
