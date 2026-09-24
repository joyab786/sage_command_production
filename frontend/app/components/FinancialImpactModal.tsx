"use client";

import React, { useState } from 'react';
import * as api from '../../lib/api';

interface FinancialImpactModalProps {
  isOpen: boolean;
  onClose: () => void;
  customerId?: string;
  supplierId?: string;
  assetId?: string;
}

interface FinancialValue {
  amount: number | null;
  currency: string | null;
  value_type: string;
  provenance: string;
  confidence: string;
  source_reference?: string;
}

interface ImpactFactor {
  category: string;
  value: FinancialValue;
  confidence: string;
  provenance: string;
  explanation: string;
  data_quality_issues: string[];
}

interface Assessment {
  assessment_id: string;
  assessment_timestamp: string;
  scenario: { scenario_name: string };
  confidence: string;
  confidence_rationale: string;
  aggregation_status: string;
  total_exposure: FinancialValue;
  factors: ImpactFactor[];
  data_quality_issues: string[];
  known_limitations: string[];
}

const CONFIDENCE_COLOR: Record<string, string> = {
  HIGH: '#22c55e',
  MEDIUM: '#eab308',
  LOW: '#f97316',
  INSUFFICIENT_DATA: '#94a3b8',
};

const CONFIDENCE_LABEL: Record<string, string> = {
  HIGH: 'High',
  MEDIUM: 'Medium',
  LOW: 'Low',
  INSUFFICIENT_DATA: 'Insufficient Data',
};

const CATEGORY_ICONS: Record<string, string> = {
  REVENUE_EXPOSURE: '📈',
  COST_EXPOSURE: '💸',
  SERVICE_PENALTY_EXPOSURE: '⚖️',
  DOWNTIME_EXPOSURE: '⏱️',
  SUPPLIER_EXPOSURE: '🔗',
  CAPACITY_EXPOSURE: '🏭',
  CUSTOMER_EXPOSURE: '👥',
  MAINTENANCE_EXPOSURE: '🔧',
};

function fmt(v: FinancialValue): string {
  if (v.amount === null || v.amount === undefined) return 'UNKNOWN';
  const amt = v.amount.toLocaleString('en-US', { maximumFractionDigits: 2 });
  return `${v.currency ?? ''} ${amt}`.trim();
}

function fmtCategory(cat: string): string {
  return cat.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

export default function FinancialImpactModal({
  isOpen,
  onClose,
  customerId,
  supplierId,
  assetId,
}: FinancialImpactModalProps) {
  const [loading, setLoading] = useState(false);
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'overview' | 'factors' | 'metadata'>('overview');

  const runAnalysis = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.analyzeFinancialImpact({
        tenant_id: 'tenant_default',
        customer_id: customerId,
        supplier_id: supplierId,
        asset_id: assetId,
        evidence_payloads: [],
        assumptions: [],
      });
      setAssessment(data);
      setActiveTab('overview');
    } catch (err: any) {
      setError(err.message || 'Failed to run Financial Impact analysis');
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  const knownFactors = assessment?.factors.filter(f => f.value.amount !== null) ?? [];
  const unknownFactors = assessment?.factors.filter(f => f.value.amount === null) ?? [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div
        className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-full max-w-5xl max-h-[90vh] overflow-hidden flex flex-col"
        style={{ fontFamily: "'Inter', sans-serif" }}
      >
        {/* ── Header ── */}
        <div className="flex items-center justify-between p-4 border-b border-slate-800 bg-slate-800/60">
          <div className="flex items-center gap-3">
            <span className="text-2xl">💰</span>
            <div>
              <h2 className="text-white font-semibold text-lg tracking-wide">
                Financial Impact Intelligence
              </h2>
              <p className="text-slate-400 text-xs">Prompt 25 — Analytical Only</p>
            </div>
            <span className="px-2 py-0.5 text-xs font-bold uppercase tracking-wider text-amber-400 bg-amber-400/10 border border-amber-400/20 rounded">
              ANALYTICAL ONLY
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white transition-colors p-1 rounded hover:bg-slate-700"
          >
            ✕
          </button>
        </div>

        {/* ── Scrollable body ── */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">

          {/* Trigger */}
          {!assessment && !loading && (
            <div className="flex flex-col items-center justify-center py-10 gap-4">
              <div className="text-slate-400 text-center max-w-md text-sm">
                Run a deterministic financial impact assessment from operational
                intelligence signals. Requires explicit monetary assumptions — never
                invents values from risk scores.
              </div>
              <button
                id="fi-run-analysis-btn"
                onClick={runAnalysis}
                className="px-6 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg font-medium text-sm transition-colors"
              >
                Run Financial Impact Analysis
              </button>
            </div>
          )}

          {loading && (
            <div className="flex items-center justify-center py-14">
              <div className="text-slate-400 animate-pulse text-sm">
                Running deterministic financial impact calculations…
              </div>
            </div>
          )}

          {error && (
            <div className="bg-red-900/30 border border-red-700/40 text-red-300 rounded-lg p-4 text-sm">
              {error}
            </div>
          )}

          {assessment && (
            <>
              {/* Total Exposure Banner */}
              <div className="rounded-xl border border-slate-700 bg-slate-800/40 p-4 flex flex-wrap items-center justify-between gap-4">
                <div>
                  <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">
                    Total Exposure
                  </p>
                  <p className="text-2xl font-bold text-white">
                    {fmt(assessment.total_exposure)}
                  </p>
                  <p className="text-slate-500 text-xs mt-1">
                    Aggregation: {assessment.aggregation_status.replace(/_/g, ' ')}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">
                    Overall Confidence
                  </p>
                  <span
                    className="px-3 py-1 rounded-full text-sm font-semibold"
                    style={{
                      background: `${CONFIDENCE_COLOR[assessment.confidence]}20`,
                      color: CONFIDENCE_COLOR[assessment.confidence],
                      border: `1px solid ${CONFIDENCE_COLOR[assessment.confidence]}40`,
                    }}
                  >
                    {CONFIDENCE_LABEL[assessment.confidence] ?? assessment.confidence}
                  </span>
                  <p className="text-slate-500 text-xs mt-1.5">
                    Scenario: {assessment.scenario.scenario_name}
                  </p>
                </div>
              </div>

              {/* Tabs */}
              <div className="flex gap-2 border-b border-slate-800">
                {(['overview', 'factors', 'metadata'] as const).map(tab => (
                  <button
                    key={tab}
                    id={`fi-tab-${tab}`}
                    onClick={() => setActiveTab(tab)}
                    className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
                      activeTab === tab
                        ? 'text-indigo-400 border-indigo-400'
                        : 'text-slate-500 border-transparent hover:text-slate-300'
                    }`}
                  >
                    {tab.charAt(0).toUpperCase() + tab.slice(1)}
                  </button>
                ))}
              </div>

              {/* Tab: Overview */}
              {activeTab === 'overview' && (
                <div className="space-y-3">
                  <p className="text-slate-400 text-sm">{assessment.confidence_rationale}</p>

                  {/* Known factors summary */}
                  {knownFactors.length > 0 && (
                    <div className="space-y-2">
                      <p className="text-slate-400 text-xs uppercase tracking-wider">
                        Quantified Exposure
                      </p>
                      {knownFactors.map(f => (
                        <div
                          key={f.category}
                          className="flex items-center justify-between bg-slate-800/50 rounded-lg px-4 py-3 border border-slate-700/50"
                        >
                          <div className="flex items-center gap-2">
                            <span>{CATEGORY_ICONS[f.category] ?? '📊'}</span>
                            <span className="text-slate-300 text-sm">{fmtCategory(f.category)}</span>
                          </div>
                          <div className="flex items-center gap-3">
                            <span className="text-white font-medium text-sm">{fmt(f.value)}</span>
                            <span
                              className="text-xs px-1.5 py-0.5 rounded"
                              style={{
                                background: `${CONFIDENCE_COLOR[f.confidence]}15`,
                                color: CONFIDENCE_COLOR[f.confidence],
                              }}
                            >
                              {CONFIDENCE_LABEL[f.confidence] ?? f.confidence}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Unknown factors */}
                  {unknownFactors.length > 0 && (
                    <div className="space-y-2">
                      <p className="text-slate-400 text-xs uppercase tracking-wider">
                        Insufficient Data ({unknownFactors.length} categories)
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {unknownFactors.map(f => (
                          <span
                            key={f.category}
                            className="text-xs px-2 py-1 rounded bg-slate-800 text-slate-500 border border-slate-700"
                          >
                            {CATEGORY_ICONS[f.category] ?? '📊'} {fmtCategory(f.category)}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Tab: Factors */}
              {activeTab === 'factors' && (
                <div className="space-y-3">
                  {assessment.factors.map(f => (
                    <div
                      key={f.category}
                      className="bg-slate-800/40 rounded-lg border border-slate-700/50 p-4 space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span>{CATEGORY_ICONS[f.category] ?? '📊'}</span>
                          <span className="text-slate-200 font-medium text-sm">{fmtCategory(f.category)}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-white text-sm font-semibold">
                            {fmt(f.value)}
                          </span>
                          <span
                            className="text-xs px-1.5 py-0.5 rounded"
                            style={{
                              background: `${CONFIDENCE_COLOR[f.confidence]}15`,
                              color: CONFIDENCE_COLOR[f.confidence],
                            }}
                          >
                            {CONFIDENCE_LABEL[f.confidence] ?? f.confidence}
                          </span>
                        </div>
                      </div>
                      {f.explanation && (
                        <p className="text-slate-400 text-xs">{f.explanation}</p>
                      )}
                      <div className="flex items-center gap-4 text-xs text-slate-500">
                        <span>Provenance: {f.value.provenance}</span>
                        {f.data_quality_issues.length > 0 && (
                          <span className="text-amber-500">
                            ⚠ {f.data_quality_issues[0]}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Tab: Metadata */}
              {activeTab === 'metadata' && (
                <div className="space-y-4 text-sm">
                  <div className="grid grid-cols-2 gap-3">
                    {[
                      ['Assessment ID', assessment.assessment_id],
                      ['Timestamp', new Date(assessment.assessment_timestamp).toLocaleString()],
                      ['Scenario', assessment.scenario.scenario_name],
                      ['Aggregation', assessment.aggregation_status],
                    ].map(([k, v]) => (
                      <div key={k} className="bg-slate-800/40 rounded-lg p-3 border border-slate-700/50">
                        <p className="text-slate-500 text-xs mb-1">{k}</p>
                        <p className="text-slate-200 text-xs font-mono break-all">{v}</p>
                      </div>
                    ))}
                  </div>

                  {assessment.data_quality_issues.length > 0 && (
                    <div>
                      <p className="text-slate-400 text-xs uppercase tracking-wider mb-2">Data Quality Issues</p>
                      {assessment.data_quality_issues.map((issue, i) => (
                        <p key={i} className="text-amber-400 text-xs">⚠ {issue}</p>
                      ))}
                    </div>
                  )}

                  {assessment.known_limitations.length > 0 && (
                    <div>
                      <p className="text-slate-400 text-xs uppercase tracking-wider mb-2">Known Limitations</p>
                      {assessment.known_limitations.map((lim, i) => (
                        <p key={i} className="text-slate-400 text-xs">• {lim}</p>
                      ))}
                    </div>
                  )}

                  <div className="bg-indigo-900/20 border border-indigo-700/30 rounded-lg p-3 text-xs text-indigo-300">
                    <strong>ANALYTICAL ONLY:</strong> This assessment does not execute financial
                    transactions, mutate operational systems, or trigger payments, procurement,
                    or supply chain actions. All values are estimates requiring explicit
                    monetary assumptions.
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* ── Footer ── */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-slate-800 bg-slate-900">
          <span className="text-xs text-slate-500">Financial Impact Intelligence · Prompt 25 · Analytical Only</span>
          <div className="flex gap-2">
            {assessment && (
              <button
                id="fi-re-analyze-btn"
                onClick={runAnalysis}
                className="px-3 py-1.5 text-xs bg-slate-700 hover:bg-slate-600 text-slate-200 rounded transition-colors"
              >
                Re-analyze
              </button>
            )}
            <button
              onClick={onClose}
              className="px-3 py-1.5 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded transition-colors"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
