export interface TenderListItem {
  tender_id: string;
  version: number;
  work_name: string | null;
  est_pac: number | null;
  publish_date: string | null;
  bid_end_date: string | null;
  organisation: string | null;
  short_bid_submission_window_days: number;
  anomaly_score: number;
  if_score_norm: number;
  lof_score_norm: number;
  status_badge: string;
  requires_award_data: boolean;
  audit_count: number;
  latest_audit_action: string | null;
}

export interface ShapWaterfallItem {
  feature: string;
  label: string;
  value: number;
  impact: number;
  direction: 'elevating' | 'moderating';
  plain_english: string;
}

export interface AuditLogItem {
  id: number;
  tender_id: string;
  tender_version: number;
  auditor_name: string | null;
  auditor_action: string;
  justification: string | null;
  timestamp: string;
}

export interface TenderDetail {
  tender_id: string;
  version: number;
  work_name: string | null;
  est_pac: number | null;
  publish_date: string | null;
  bid_end_date: string | null;
  organisation: string | null;
  work_category: string | null;
  short_bid_submission_window_days: number;
  requires_award_data: boolean;
  anomaly_score: number;
  if_score_norm: number;
  lof_score_norm: number;
  status_badge: string;
  rate_deviation_pct: number;
  boq_unbalanced_bidding_index: number;
  standard_bitumen_spec_ratio: number;
  shap_base_value: number;
  shap_waterfall: ShapWaterfallItem[];
  audit_logs: AuditLogItem[];
}

export interface SummaryMetrics {
  total_tenders: number;
  high_variance_count: number;
  moderate_variance_count: number;
  baseline_normal_count: number;
  audited_count: number;
  avg_anomaly_score: number;
}
