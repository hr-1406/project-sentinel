import React, { useState, useMemo } from 'react';
import type { TenderListItem } from '../types';
import { Search, ChevronRight, ArrowUpDown, Filter, Clock, CheckCircle } from 'lucide-react';

interface TriageTableProps {
  tenders: TenderListItem[];
  onSelectTender: (tenderId: string) => void;
  activeFilter: string;
}

export const TriageTable: React.FC<TriageTableProps> = ({
  tenders,
  onSelectTender,
  activeFilter,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [sortField, setSortField] = useState<'score' | 'pac' | 'window'>('score');
  const [sortAsc, setSortAsc] = useState(false);

  // Currency formatter for Indian Rupees
  const formatINR = (val: number | null) => {
    if (val === null || val === undefined) return '—';
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0,
    }).format(val);
  };

  // Filter and search logic
  const filteredTenders = useMemo(() => {
    return tenders.filter((t) => {
      // Metric card filter
      if (activeFilter === 'HIGH' && t.anomaly_score < 0.75) return false;
      if (activeFilter === 'MODERATE' && (t.anomaly_score < 0.50 || t.anomaly_score >= 0.75)) return false;
      if (activeFilter === 'BASELINE' && t.anomaly_score >= 0.50) return false;
      if (activeFilter === 'AUDITED' && t.audit_count === 0) return false;

      // Search query
      if (!searchQuery.trim()) return true;
      const q = searchQuery.toLowerCase();
      return (
        t.tender_id.toLowerCase().includes(q) ||
        (t.work_name && t.work_name.toLowerCase().includes(q)) ||
        (t.organisation && t.organisation.toLowerCase().includes(q))
      );
    });
  }, [tenders, activeFilter, searchQuery]);

  // Sorting logic
  const sortedTenders = useMemo(() => {
    return [...filteredTenders].sort((a, b) => {
      let comparison = 0;
      if (sortField === 'score') {
        comparison = a.anomaly_score - b.anomaly_score;
      } else if (sortField === 'pac') {
        comparison = (a.est_pac || 0) - (b.est_pac || 0);
      } else if (sortField === 'window') {
        comparison = a.short_bid_submission_window_days - b.short_bid_submission_window_days;
      }
      return sortAsc ? comparison : -comparison;
    });
  }, [filteredTenders, sortField, sortAsc]);

  const handleSort = (field: 'score' | 'pac' | 'window') => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(false);
    }
  };

  return (
    <div className="bg-slate-900/80 border border-slate-800 rounded-2xl shadow-xl overflow-hidden backdrop-blur">
      {/* Search & Toolbar Header */}
      <div className="p-4 border-b border-slate-800 flex flex-col sm:flex-row items-center justify-between gap-3">
        <div className="relative w-full sm:w-80">
          <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            placeholder="Search tender ID, road name, section..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-3 py-1.5 bg-slate-950/80 border border-slate-800 rounded-lg text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
          />
        </div>

        <div className="flex items-center space-x-2 text-xs text-slate-400">
          <Filter className="h-3.5 w-3.5 text-slate-500" />
          <span>
            Showing <strong className="text-slate-200">{sortedTenders.length}</strong> of{' '}
            {tenders.length} tenders
          </span>
        </div>
      </div>

      {/* Tenders Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs text-slate-300">
          <thead className="bg-slate-950/60 text-slate-400 text-[11px] uppercase tracking-wider font-semibold border-b border-slate-800">
            <tr>
              <th
                onClick={() => handleSort('score')}
                className="py-3 px-4 cursor-pointer hover:text-slate-200 transition"
              >
                <div className="flex items-center space-x-1.5">
                  <span>Ensemble Score</span>
                  <ArrowUpDown className="h-3 w-3" />
                </div>
              </th>
              <th className="py-3 px-4">Triage Status</th>
              <th className="py-3 px-4">Tender Reference ID</th>
              <th className="py-3 px-4 min-w-[280px]">Work Description</th>
              <th
                onClick={() => handleSort('pac')}
                className="py-3 px-4 cursor-pointer hover:text-slate-200 transition text-right"
              >
                <div className="flex items-center justify-end space-x-1.5">
                  <span>Est. PAC</span>
                  <ArrowUpDown className="h-3 w-3" />
                </div>
              </th>
              <th
                onClick={() => handleSort('window')}
                className="py-3 px-4 cursor-pointer hover:text-slate-200 transition text-center"
              >
                <div className="flex items-center justify-center space-x-1.5">
                  <span>Bid Window</span>
                  <ArrowUpDown className="h-3 w-3" />
                </div>
              </th>
              <th className="py-3 px-4 text-center">Audit Status</th>
              <th className="py-3 px-4 text-center">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {sortedTenders.length === 0 ? (
              <tr>
                <td colSpan={8} className="py-12 text-center text-slate-500 text-xs">
                  No tenders match the selected filters or search terms.
                </td>
              </tr>
            ) : (
              sortedTenders.map((tender) => {
                const score = tender.anomaly_score;
                const scorePercent = Math.min(100, Math.max(0, Math.round(score * 100)));

                // Neutral status styling
                let badgeClass = 'bg-slate-800 text-slate-300 border-slate-700';
                let progressClass = 'bg-emerald-500';

                if (score >= 0.75) {
                  badgeClass = 'bg-rose-500/10 text-rose-400 border-rose-500/30';
                  progressClass = 'bg-rose-500';
                } else if (score >= 0.50) {
                  badgeClass = 'bg-amber-500/10 text-amber-400 border-amber-500/30';
                  progressClass = 'bg-amber-500';
                } else {
                  badgeClass = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30';
                  progressClass = 'bg-emerald-500';
                }

                return (
                  <tr
                    key={tender.tender_id}
                    onClick={() => onSelectTender(tender.tender_id)}
                    className="hover:bg-slate-800/40 cursor-pointer transition group"
                  >
                    {/* Anomaly Score Progress */}
                    <td className="py-3.5 px-4 whitespace-nowrap">
                      <div className="flex items-center space-x-2.5">
                        <span className="font-mono font-bold text-slate-100 w-11">
                          {score.toFixed(4)}
                        </span>
                        <div className="w-16 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all duration-300 ${progressClass}`}
                            style={{ width: `${scorePercent}%` }}
                          />
                        </div>
                      </div>
                    </td>

                    {/* Status Badge */}
                    <td className="py-3.5 px-4 whitespace-nowrap">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium border ${badgeClass}`}
                      >
                        {tender.status_badge}
                      </span>
                    </td>

                    {/* Tender ID */}
                    <td className="py-3.5 px-4 font-mono text-[11px] text-indigo-300 whitespace-nowrap">
                      {tender.tender_id}
                    </td>

                    {/* Work Description */}
                    <td className="py-3.5 px-4">
                      <div className="text-slate-200 line-clamp-2 leading-relaxed" title={tender.work_name || ''}>
                        {tender.work_name || '—'}
                      </div>
                      {tender.organisation && (
                        <div className="text-[10px] text-slate-500 mt-0.5">
                          Section: {tender.organisation}
                        </div>
                      )}
                    </td>

                    {/* Est. PAC */}
                    <td className="py-3.5 px-4 font-mono text-right font-medium text-slate-200 whitespace-nowrap">
                      {formatINR(tender.est_pac)}
                    </td>

                    {/* Bid Window */}
                    <td className="py-3.5 px-4 text-center whitespace-nowrap">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium ${
                          tender.short_bid_submission_window_days <= 7
                            ? 'bg-rose-500/10 text-rose-300 border border-rose-500/20'
                            : 'bg-slate-800 text-slate-300'
                        }`}
                      >
                        <Clock className="h-3 w-3 mr-1 opacity-70" />
                        {tender.short_bid_submission_window_days}d
                      </span>
                    </td>

                    {/* Audit Status */}
                    <td className="py-3.5 px-4 text-center whitespace-nowrap">
                      {tender.audit_count > 0 ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-indigo-500/15 text-indigo-300 border border-indigo-500/30">
                          <CheckCircle className="h-3 w-3 mr-1 text-indigo-400" />
                          {tender.latest_audit_action || 'Audited'}
                        </span>
                      ) : (
                        <span className="text-[11px] text-slate-500">Unreviewed</span>
                      )}
                    </td>

                    {/* Action Arrow */}
                    <td className="py-3.5 px-4 text-center whitespace-nowrap text-slate-500 group-hover:text-indigo-400 transition">
                      <ChevronRight className="h-4 w-4 inline" />
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
