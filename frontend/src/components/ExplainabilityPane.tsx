import React from 'react';
import type { TenderDetail } from '../types';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
} from 'recharts';
import { Info, Activity, Globe, Users } from 'lucide-react';

interface ExplainabilityPaneProps {
  tender: TenderDetail;
}

export const ExplainabilityPane: React.FC<ExplainabilityPaneProps> = ({ tender }) => {
  // Prepare data for the SHAP attribution chart
  const chartData = tender.shap_waterfall.map((item) => ({
    name: item.label,
    impact: item.impact,
    feature: item.feature,
    value: item.value,
    direction: item.direction,
    plain_english: item.plain_english,
  }));

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="bg-slate-900 border border-slate-700 p-3 rounded-lg shadow-xl text-xs max-w-xs">
          <div className="font-semibold text-slate-100 mb-1">{data.name}</div>
          <div className="text-slate-300 mb-1">
            Raw Value: <span className="font-mono text-indigo-300">{data.value}</span>
          </div>
          <div className="text-slate-300 mb-2">
            SHAP Attribution: <span className="font-mono font-bold text-slate-100">{data.impact > 0 ? `+${data.impact.toFixed(4)}` : data.impact.toFixed(4)}</span>
          </div>
          <div className="text-[11px] text-slate-400 bg-slate-950 p-2 rounded border border-slate-800">
            {data.plain_english}
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="space-y-5">
      {/* Overview Cards: Ensemble Score + Base Value */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-5 backdrop-blur">
        <div className="flex items-center justify-between pb-4 border-b border-slate-800">
          <div>
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Ensemble Anomaly Index
            </span>
            <div className="flex items-baseline space-x-2 mt-1">
              <span className="text-3xl font-extrabold font-mono text-slate-100 tracking-tight">
                {tender.anomaly_score.toFixed(4)}
              </span>
              <span className="text-xs text-slate-400">/ 1.0000</span>
            </div>
          </div>
          <div className="text-right">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Surrogate Base Value (Expected)
            </span>
            <div className="text-xl font-mono text-slate-300 mt-1">
              {tender.shap_base_value.toFixed(4)}
            </div>
          </div>
        </div>

        {/* Global vs Local Deviation Breakdown */}
        <div className="grid grid-cols-2 gap-3 mt-4">
          <div className="bg-slate-950/60 border border-slate-800/80 rounded-xl p-3">
            <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
              <span className="flex items-center space-x-1">
                <Globe className="h-3.5 w-3.5 text-sky-400" />
                <span>Global Outlier (IF)</span>
              </span>
              <span className="font-mono font-medium text-slate-200">
                {tender.if_score_norm.toFixed(4)}
              </span>
            </div>
            <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-sky-400 rounded-full"
                style={{ width: `${Math.round(tender.if_score_norm * 100)}%` }}
              />
            </div>
            <span className="text-[10px] text-slate-500 mt-1 block">
              Isolation Forest across statewide distribution
            </span>
          </div>

          <div className="bg-slate-950/60 border border-slate-800/80 rounded-xl p-3">
            <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
              <span className="flex items-center space-x-1">
                <Users className="h-3.5 w-3.5 text-purple-400" />
                <span>Local Peer Variance (LOF)</span>
              </span>
              <span className="font-mono font-medium text-slate-200">
                {tender.lof_score_norm.toFixed(4)}
              </span>
            </div>
            <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-purple-400 rounded-full"
                style={{ width: `${Math.round(tender.lof_score_norm * 100)}%` }}
              />
            </div>
            <span className="text-[10px] text-slate-500 mt-1 block">
              Local Outlier Factor vs k-nearest peer tenders
            </span>
          </div>
        </div>
      </div>

      {/* SHAP Waterfall / Feature Impact Chart */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-5 backdrop-blur">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center space-x-2">
            <Activity className="h-4 w-4 text-indigo-400" />
            <h3 className="text-sm font-bold text-slate-200">
              SHAP Feature Attribution Waterfall
            </h3>
          </div>
          <span className="text-[11px] text-slate-500">
            Additive contributions relative to Base ({tender.shap_base_value.toFixed(3)})
          </span>
        </div>

        <p className="text-xs text-slate-400 mb-4 leading-relaxed">
          Shows how each procurement dimension pushes the anomaly score higher (elevating risk of divergence) or lower (within normal peer patterns).
        </p>

        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              layout="vertical"
              data={chartData}
              margin={{ top: 10, right: 25, left: 20, bottom: 5 }}
            >
              <XAxis
                type="number"
                domain={['dataMin - 0.05', 'dataMax + 0.05']}
                stroke="#64748b"
                fontSize={11}
                tickFormatter={(val) => (val > 0 ? `+${val.toFixed(2)}` : val.toFixed(2))}
              />
              <YAxis
                type="category"
                dataKey="name"
                stroke="#94a3b8"
                fontSize={11}
                width={150}
                tickLine={false}
              />
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine x={0} stroke="#475569" strokeDasharray="3 3" />
              <Bar dataKey="impact" radius={[4, 4, 4, 4]}>
                {chartData.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={entry.impact >= 0 ? '#f43f5e' : '#10b981'}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Plain-English Audit Translation List */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-5 backdrop-blur">
        <div className="flex items-center space-x-2 mb-3">
          <Info className="h-4 w-4 text-indigo-400" />
          <h3 className="text-sm font-bold text-slate-200">
            Auditor Plain-English Explanations
          </h3>
        </div>

        <div className="space-y-2.5">
          {tender.shap_waterfall.map((item, idx) => {
            const isElevating = item.impact >= 0;
            return (
              <div
                key={idx}
                className={`p-3 rounded-xl border text-xs flex items-start space-x-3 ${
                  isElevating
                    ? 'bg-rose-500/5 border-rose-500/20 text-slate-300'
                    : 'bg-emerald-500/5 border-emerald-500/20 text-slate-300'
                }`}
              >
                <div
                  className={`px-2 py-0.5 rounded font-mono font-bold text-[11px] whitespace-nowrap mt-0.5 ${
                    isElevating
                      ? 'bg-rose-500/20 text-rose-300'
                      : 'bg-emerald-500/20 text-emerald-300'
                  }`}
                >
                  {isElevating ? `+${item.impact.toFixed(3)}` : item.impact.toFixed(3)}
                </div>
                <div>
                  <div className="font-semibold text-slate-200">{item.label}</div>
                  <div className="text-slate-400 mt-0.5">{item.plain_english}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
