import React, { useEffect, useState } from 'react';
import type { TenderDetail, AuditLogItem } from '../types';
import { ExplainabilityPane } from './ExplainabilityPane';
import { AuditPanel } from './AuditPanel';
import { ArrowLeft, Loader2, AlertCircle, RefreshCw } from 'lucide-react';

interface InvestigationViewProps {
  tenderId: string;
  onBack: () => void;
  onRefreshParent: () => void;
}

export const InvestigationView: React.FC<InvestigationViewProps> = ({
  tenderId,
  onBack,
  onRefreshParent,
}) => {
  const [tender, setTender] = useState<TenderDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTenderDetail = async () => {
    setLoading(true);
    setError(null);
    try {
      const encodedId = encodeURIComponent(tenderId);
      const res = await fetch(`http://localhost:8000/api/tenders/${encodedId}`);
      if (!res.ok) {
        throw new Error(`Failed to load tender details (${res.status})`);
      }
      const data: TenderDetail = await res.json();
      setTender(data);
    } catch (err: any) {
      setError(err.message || 'Error fetching tender details.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTenderDetail();
  }, [tenderId]);

  const handleAuditSubmitted = (updatedLogs: AuditLogItem[]) => {
    if (tender) {
      setTender({
        ...tender,
        audit_logs: updatedLogs,
      });
      onRefreshParent();
    }
  };

  if (loading) {
    return (
      <div className="py-24 flex flex-col items-center justify-center space-y-3">
        <Loader2 className="h-8 w-8 text-indigo-400 animate-spin" />
        <p className="text-xs text-slate-400">Loading explainability attributions and tender context...</p>
      </div>
    );
  }

  if (error || !tender) {
    return (
      <div className="p-8 bg-slate-900 border border-slate-800 rounded-2xl text-center space-y-4">
        <AlertCircle className="h-10 w-10 text-rose-400 mx-auto" />
        <h3 className="text-base font-bold text-slate-200">Unable to load tender details</h3>
        <p className="text-xs text-slate-400 max-w-md mx-auto">{error || 'Tender record not found.'}</p>
        <div className="flex justify-center space-x-3">
          <button
            onClick={onBack}
            className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs rounded-lg transition"
          >
            ← Return to Triage Queue
          </button>
          <button
            onClick={fetchTenderDetail}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs rounded-lg transition flex items-center space-x-1.5"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>Retry</span>
          </button>
        </div>
      </div>
    );
  }

  // Derive badge styling
  let badgeStyle = 'bg-slate-800 text-slate-300 border-slate-700';
  if (tender.anomaly_score >= 0.75) {
    badgeStyle = 'bg-rose-500/10 text-rose-400 border-rose-500/30';
  } else if (tender.anomaly_score >= 0.50) {
    badgeStyle = 'bg-amber-500/10 text-amber-400 border-amber-500/30';
  } else {
    badgeStyle = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30';
  }

  return (
    <div className="space-y-6">
      {/* Top Banner Navigation & Context */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-900/90 border border-slate-800 p-4 rounded-2xl backdrop-blur">
        <div className="flex items-center space-x-3">
          <button
            onClick={onBack}
            className="p-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition"
            title="Back to Triage Queue"
          >
            <ArrowLeft className="h-5 w-5" />
          </button>
          <div>
            <div className="flex items-center space-x-2.5">
              <span className="font-mono text-sm font-bold text-indigo-300">
                {tender.tender_id}
              </span>
              <span className="text-[10px] text-slate-500 font-mono">v{tender.version}</span>
              <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border ${badgeStyle}`}>
                {tender.status_badge}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Detailed Explainability Triage & Human-in-the-Loop Audit Decisioning
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-3 text-xs">
          <button
            onClick={fetchTenderDetail}
            className="px-3 py-1.5 text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg border border-slate-700/60 transition flex items-center space-x-1.5"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>Reload</span>
          </button>
        </div>
      </div>

      {/* Investigation Split-View Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
        {/* Left Pane: SHAP Explainability & Anomaly Metrics */}
        <ExplainabilityPane tender={tender} />

        {/* Right Pane: Extracted Tender Metadata & Audit Action Form */}
        <AuditPanel tender={tender} onAuditSubmitted={handleAuditSubmitted} />
      </div>
    </div>
  );
};
