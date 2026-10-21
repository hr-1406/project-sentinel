import React, { useState } from 'react';
import type { TenderDetail, AuditLogItem } from '../types';
import {
  FileText,
  AlertTriangle,
  Send,
  History,
  Calendar,
  Building,
  Tag,
  CheckCircle2,
  Clock,
  ShieldAlert,
} from 'lucide-react';

interface AuditPanelProps {
  tender: TenderDetail;
  onAuditSubmitted: (updatedLogs: AuditLogItem[]) => void;
}

export const AuditPanel: React.FC<AuditPanelProps> = ({
  tender,
  onAuditSubmitted,
}) => {
  const [action, setAction] = useState<string>('Request Clarifying Documentation');
  const [justification, setJustification] = useState<string>('');
  const [auditorName, setAuditorName] = useState<string>('Auditor (LSGD Audit Wing)');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const formatINR = (val: number | null) => {
    if (val === null || val === undefined) return '—';
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0,
    }).format(val);
  };

  const handleSubmitAudit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!justification.trim() || justification.trim().length < 5) {
      setErrorMessage('Please provide a meaningful justification note (minimum 5 characters).');
      return;
    }

    setIsSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      // tender_id may have slashes, encode each path component or direct URL
      const encodedId = encodeURIComponent(tender.tender_id);
      const res = await fetch(`http://localhost:8000/api/tenders/${encodedId}/audit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          auditor_action: action,
          justification: justification.trim(),
          auditor_name: auditorName.trim() || 'Auditor',
        }),
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Failed to submit audit decision.');
      }

      const updatedLogs: AuditLogItem[] = await res.json();
      onAuditSubmitted(updatedLogs);
      setJustification('');
      setSuccessMessage(`Decision "${action}" recorded in audit trail.`);
      setTimeout(() => setSuccessMessage(null), 4000);
    } catch (err: any) {
      setErrorMessage(err.message || 'Error recording audit action.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* Extracted Tender Metadata */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-5 backdrop-blur">
        <div className="flex items-center space-x-2 pb-3 mb-4 border-b border-slate-800">
          <FileText className="h-4 w-4 text-indigo-400" />
          <h3 className="text-sm font-bold text-slate-200">
            Extracted Tender Context (NIT Silver Layer)
          </h3>
        </div>

        <div className="space-y-3 text-xs">
          <div>
            <span className="text-slate-400 font-medium">Work Title:</span>
            <p className="text-slate-200 mt-0.5 leading-relaxed bg-slate-950/60 p-2.5 rounded-lg border border-slate-800">
              {tender.work_name || 'Not specified in NIT'}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="bg-slate-950/60 p-2.5 rounded-lg border border-slate-800">
              <div className="flex items-center space-x-1 text-slate-400 mb-1">
                <Building className="h-3.5 w-3.5 text-slate-500" />
                <span>LSGD Section / Office</span>
              </div>
              <div className="font-medium text-slate-200 truncate">
                {tender.organisation || 'LSGD Kerala'}
              </div>
            </div>

            <div className="bg-slate-950/60 p-2.5 rounded-lg border border-slate-800">
              <div className="flex items-center space-x-1 text-slate-400 mb-1">
                <Tag className="h-3.5 w-3.5 text-slate-500" />
                <span>Estimated PAC</span>
              </div>
              <div className="font-mono font-bold text-slate-100">
                {formatINR(tender.est_pac)}
              </div>
            </div>

            <div className="bg-slate-950/60 p-2.5 rounded-lg border border-slate-800">
              <div className="flex items-center space-x-1 text-slate-400 mb-1">
                <Calendar className="h-3.5 w-3.5 text-slate-500" />
                <span>Published Date</span>
              </div>
              <div className="font-mono text-slate-200">
                {tender.publish_date || '—'}
              </div>
            </div>

            <div className="bg-slate-950/60 p-2.5 rounded-lg border border-slate-800">
              <div className="flex items-center space-x-1 text-slate-400 mb-1">
                <Clock className="h-3.5 w-3.5 text-slate-500" />
                <span>Bid End Date ({tender.short_bid_submission_window_days}d window)</span>
              </div>
              <div className="font-mono text-slate-200">
                {tender.bid_end_date || '—'}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Pre-bid BOQ Data Notice */}
      {tender.requires_award_data && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-2xl p-4 text-xs text-amber-300">
          <div className="flex items-start space-x-2.5">
            <AlertTriangle className="h-4 w-4 text-amber-400 mt-0.5 shrink-0" />
            <div>
              <div className="font-bold text-amber-200">
                Notice: Pre-Bid BOQ Template (Pending Comparative Statement)
              </div>
              <p className="mt-1 text-amber-300/90 leading-relaxed">
                This tender was ingested with a blank pre-bid Bill of Quantities template lacking awarded contractor bid rates. The rate deviation baseline is modeled probabilistically until financial bid opening and comparative statements are cataloged.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Human-in-the-Loop Auditor Resolution Form */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-5 backdrop-blur">
        <div className="flex items-center space-x-2 pb-3 mb-4 border-b border-slate-800">
          <ShieldAlert className="h-4 w-4 text-indigo-400" />
          <h3 className="text-sm font-bold text-slate-200">
            Human-in-the-Loop Auditor Resolution
          </h3>
        </div>

        <form onSubmit={handleSubmitAudit} className="space-y-3.5 text-xs">
          <div>
            <label className="block text-slate-300 font-medium mb-1.5">
              Auditor Triage Action
            </label>
            <select
              value={action}
              onChange={(e) => setAction(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            >
              <option value="Acknowledge & Clear">Acknowledge & Clear (Within Acceptable Parameters)</option>
              <option value="Request Clarifying Documentation">Request Clarifying Documentation from LSGD Engineer</option>
              <option value="Escalate for Technical Review">Escalate for Detailed Technical Review</option>
            </select>
          </div>

          <div>
            <label className="block text-slate-300 font-medium mb-1.5">
              Auditor Identity / Reference
            </label>
            <input
              type="text"
              value={auditorName}
              onChange={(e) => setAuditorName(e.target.value)}
              placeholder="E.g., Senior Technical Auditor"
              className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label className="block text-slate-300 font-medium mb-1.5">
              Justification & Audit Finding Notes <span className="text-rose-400">*</span>
            </label>
            <textarea
              rows={3}
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              placeholder="State clear, neutral rationale for this decision (e.g., Short window verified against LSGD emergency repair circular #42...)"
              className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 resize-none"
            />
          </div>

          {errorMessage && (
            <div className="p-2.5 bg-rose-500/10 border border-rose-500/30 text-rose-300 rounded-lg text-xs">
              {errorMessage}
            </div>
          )}

          {successMessage && (
            <div className="p-2.5 bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 rounded-lg text-xs flex items-center space-x-1.5">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <span>{successMessage}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full py-2.5 px-4 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 text-white font-medium rounded-lg transition flex items-center justify-center space-x-2 text-xs shadow-lg shadow-indigo-600/20"
          >
            <Send className="h-3.5 w-3.5" />
            <span>{isSubmitting ? 'Recording Audit Action...' : 'Submit Auditor Decision'}</span>
          </button>
        </form>
      </div>

      {/* Historical Audit Trail */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-5 backdrop-blur">
        <div className="flex items-center space-x-2 pb-3 mb-3 border-b border-slate-800">
          <History className="h-4 w-4 text-indigo-400" />
          <h3 className="text-sm font-bold text-slate-200">
            Historical Audit Log ({tender.audit_logs.length})
          </h3>
        </div>

        {tender.audit_logs.length === 0 ? (
          <p className="text-xs text-slate-500 py-4 text-center">
            No previous audit decisions recorded for this tender.
          </p>
        ) : (
          <div className="space-y-3">
            {tender.audit_logs.map((log) => (
              <div
                key={log.id}
                className="bg-slate-950/70 border border-slate-800 rounded-xl p-3 text-xs space-y-1.5"
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-indigo-300">{log.auditor_action}</span>
                  <span className="text-[10px] text-slate-500 font-mono">
                    {new Date(log.timestamp).toLocaleString('en-IN', {
                      dateStyle: 'short',
                      timeStyle: 'short',
                    })}
                  </span>
                </div>
                <p className="text-slate-300 leading-relaxed bg-slate-900/60 p-2 rounded border border-slate-800/80">
                  {log.justification}
                </p>
                <div className="text-[10px] text-slate-500 flex justify-between">
                  <span>By: {log.auditor_name || 'Auditor'}</span>
                  <span>Tender Version: v{log.tender_version}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
