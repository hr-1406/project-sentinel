import React from 'react';
import type { SummaryMetrics } from '../types';
import { Layers, AlertCircle, AlertTriangle, CheckCircle2, UserCheck } from 'lucide-react';

interface SummaryCardsProps {
  metrics: SummaryMetrics | null;
  activeFilter: string;
  onFilterChange: (filter: string) => void;
}

export const SummaryCards: React.FC<SummaryCardsProps> = ({
  metrics,
  activeFilter,
  onFilterChange,
}) => {
  if (!metrics) return null;

  const cards = [
    {
      id: 'ALL',
      title: 'Total Triage Queue',
      value: metrics.total_tenders,
      subtitle: `Avg Anomaly Index: ${metrics.avg_anomaly_score.toFixed(3)}`,
      icon: Layers,
      color: 'slate',
      border: activeFilter === 'ALL' ? 'border-indigo-500 ring-1 ring-indigo-500' : 'border-slate-800',
    },
    {
      id: 'HIGH',
      title: 'High Statistical Variance',
      value: metrics.high_variance_count,
      subtitle: 'Score ≥ 0.75 • Priority Review',
      icon: AlertCircle,
      color: 'rose',
      border: activeFilter === 'HIGH' ? 'border-rose-500 ring-1 ring-rose-500' : 'border-slate-800',
    },
    {
      id: 'MODERATE',
      title: 'Moderate Variance',
      value: metrics.moderate_variance_count,
      subtitle: 'Score 0.50 – 0.74 • Secondary Audit',
      icon: AlertTriangle,
      color: 'amber',
      border: activeFilter === 'MODERATE' ? 'border-amber-500 ring-1 ring-amber-500' : 'border-slate-800',
    },
    {
      id: 'BASELINE',
      title: 'Within Normal Baseline',
      value: metrics.baseline_normal_count,
      subtitle: 'Score < 0.50 • Standard Workflow',
      icon: CheckCircle2,
      color: 'emerald',
      border: activeFilter === 'BASELINE' ? 'border-emerald-500 ring-1 ring-emerald-500' : 'border-slate-800',
    },
    {
      id: 'AUDITED',
      title: 'Auditor Action Recorded',
      value: metrics.audited_count,
      subtitle: 'Human-in-the-Loop Logged',
      icon: UserCheck,
      color: 'indigo',
      border: activeFilter === 'AUDITED' ? 'border-indigo-400 ring-1 ring-indigo-400' : 'border-slate-800',
    },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3.5 mb-6">
      {cards.map((c) => {
        const Icon = c.icon;
        return (
          <button
            key={c.id}
            onClick={() => onFilterChange(c.id)}
            className={`text-left p-4 rounded-xl bg-slate-900/70 hover:bg-slate-900 border transition cursor-pointer ${c.border}`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-slate-400">{c.title}</span>
              <div
                className={`p-1.5 rounded-lg ${
                  c.color === 'rose'
                    ? 'text-rose-400 bg-rose-500/10'
                    : c.color === 'amber'
                    ? 'text-amber-400 bg-amber-500/10'
                    : c.color === 'emerald'
                    ? 'text-emerald-400 bg-emerald-500/10'
                    : c.color === 'indigo'
                    ? 'text-indigo-400 bg-indigo-500/10'
                    : 'text-slate-400 bg-slate-800'
                }`}
              >
                <Icon className="h-4 w-4" />
              </div>
            </div>
            <div className="text-2xl font-bold text-slate-100 tracking-tight">{c.value}</div>
            <div className="text-[11px] text-slate-400 mt-1 truncate">{c.subtitle}</div>
          </button>
        );
      })}
    </div>
  );
};
