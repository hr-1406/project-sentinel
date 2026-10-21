import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { SummaryCards } from './components/SummaryCards';
import { TriageTable } from './components/TriageTable';
import { InvestigationView } from './components/InvestigationView';
import type { SummaryMetrics, TenderListItem } from './types';
import { AlertCircle, Loader2, RefreshCw } from 'lucide-react';

export const App: React.FC = () => {
  const [tenders, setTenders] = useState<TenderListItem[]>([]);
  const [summary, setSummary] = useState<SummaryMetrics | null>(null);
  const [selectedTenderId, setSelectedTenderId] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState<string>('ALL');
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [summaryRes, tendersRes] = await Promise.all([
        fetch('http://localhost:8000/api/summary'),
        fetch('http://localhost:8000/api/tenders'),
      ]);

      if (!summaryRes.ok || !tendersRes.ok) {
        throw new Error('Failed to connect to Sentinel backend service at http://localhost:8000');
      }

      const summaryData = await summaryRes.json();
      const tendersData = await tendersRes.json();

      setSummary(summaryData);
      setTenders(tendersData);
    } catch (err: any) {
      setError(err.message || 'Error fetching data from API.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleSelectTender = (tenderId: string) => {
    setSelectedTenderId(tenderId);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleBackToQueue = () => {
    setSelectedTenderId(null);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Header
        onRefresh={fetchData}
        isLoading={isLoading}
        selectedTenderId={selectedTenderId}
        onBackToQueue={handleBackToQueue}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-6 py-6">
        {error && (
          <div className="mb-6 p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center justify-between">
            <div className="flex items-center space-x-2.5">
              <AlertCircle className="h-4 w-4 shrink-0 text-rose-400" />
              <span>
                Backend connection error: {error}. Ensure the FastAPI server is running on port 8000.
              </span>
            </div>
            <button
              onClick={fetchData}
              className="px-3 py-1 bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 rounded-md transition font-medium flex items-center space-x-1"
            >
              <RefreshCw className="h-3 w-3" />
              <span>Retry</span>
            </button>
          </div>
        )}

        {isLoading && tenders.length === 0 ? (
          <div className="py-32 flex flex-col items-center justify-center space-y-3">
            <Loader2 className="h-8 w-8 text-indigo-400 animate-spin" />
            <p className="text-xs text-slate-400">Loading Sentinel triage queue from Gold layer...</p>
          </div>
        ) : selectedTenderId ? (
          <InvestigationView
            tenderId={selectedTenderId}
            onBack={handleBackToQueue}
            onRefreshParent={fetchData}
          />
        ) : (
          <div>
            <SummaryCards
              metrics={summary}
              activeFilter={activeFilter}
              onFilterChange={setActiveFilter}
            />

            <TriageTable
              tenders={tenders}
              onSelectTender={handleSelectTender}
              activeFilter={activeFilter}
            />
          </div>
        )}
      </main>

      <footer className="border-t border-slate-900 bg-slate-950/80 px-6 py-4 text-center text-[11px] text-slate-400">
        <p>
          Project Sentinel • Decision-Support System for Kerala LSGD Public Procurement Tenders.
        </p>
        <p className="text-slate-400 mt-0.5">
          Decision Support, Not Accusation: Statistical outlier metrics triage items for human audit and do not constitute legal or administrative findings.
        </p>
      </footer>
    </div>
  );
};

export default App;
