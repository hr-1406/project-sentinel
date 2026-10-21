import React from 'react';
import { ShieldCheck, RefreshCw, BarChart3 } from 'lucide-react';

interface HeaderProps {
  onRefresh: () => void;
  isLoading: boolean;
  selectedTenderId: string | null;
  onBackToQueue?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  onRefresh,
  isLoading,
  selectedTenderId,
  onBackToQueue,
}) => {
  return (
    <header className="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-30 px-6 py-3.5">
      <div className="max-w-7xl mx-auto flex items-center justify-between">
        <div className="flex items-center space-x-3.5">
          <div className="h-10 w-10 rounded-xl bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center space-x-2.5">
              <h1 className="text-lg font-bold text-slate-100 tracking-tight">
                Project Sentinel
              </h1>
              <span className="text-[11px] font-medium tracking-wide uppercase px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                Decision Support
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Explainable AI Anomaly Detection • Kerala LSGD Public Procurement
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-3">
          {selectedTenderId && onBackToQueue && (
            <button
              onClick={onBackToQueue}
              className="px-3 py-1.5 text-xs font-medium text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 rounded-lg border border-slate-700 transition flex items-center space-x-1.5"
            >
              <span>← Back to Triage Queue</span>
            </button>
          )}

          <div className="flex items-center text-xs text-slate-400 space-x-1.5 px-2.5 py-1 rounded-md bg-slate-800/60 border border-slate-700/50">
            <BarChart3 className="h-3.5 w-3.5 text-indigo-400" />
            <span>IF + LOF Ensemble (SHAP Surrogate)</span>
          </div>

          <button
            onClick={onRefresh}
            disabled={isLoading}
            className="p-2 text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg border border-slate-700/50 transition disabled:opacity-50"
            title="Refresh Data"
          >
            <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin text-indigo-400' : ''}`} />
          </button>
        </div>
      </div>
    </header>
  );
};
