'use client'

import React, { useState, useEffect } from 'react'
import {
  X,
  Target,
  CheckCircle2,
  AlertTriangle,
  Scale,
  BrainCircuit,
  TrendingUp,
  TrendingDown,
  Layers,
  ShieldCheck,
  Info,
  Clock,
  Sparkles,
  Database
} from 'lucide-react'

interface EvaluationRecord {
  evaluation_id: string
  prediction_id: string
  outcome_id: string
  evaluation_status: string
  prediction_type: string
  target_reference: string
  predicted_value: string | number | boolean
  observed_value: string | number | boolean
  unit?: string
  comparison_semantics: string
  absolute_error?: number
  signed_error?: number
  relative_error?: number
  directional_bias?: string
  exact_match?: boolean
  verification_reference?: string
  is_diagnostic: boolean
  eligible_for_learning: boolean
  learning_ineligibility_reason?: string
  data_mode: string
  tenant_id: string
  workspace_id: string
  plant_id: string
  evaluated_at: string
}

interface AggregateMetrics {
  prediction_type: string
  tenant_id: string
  workspace_id: string
  plant_id?: string
  data_mode: string
  total_evaluations: number
  eligible_sample_count: number
  excluded_evaluations: number
  sample_status: string
  min_sample_threshold: number
  mean_absolute_error?: number
  mean_absolute_percentage_error?: number
  root_mean_squared_error?: number
  signed_mean_error?: number
  over_predicted_count: number
  under_predicted_count: number
  exact_matched_count: number
  exact_match_rate?: number
  unverified_count: number
  deferred_count: number
  rejected_count: number
  unit?: string
}

interface OutcomeLearningModalProps {
  isOpen: boolean
  onClose: () => void
}

export default function OutcomeLearningModal({ isOpen, onClose }: OutcomeLearningModalProps) {
  const [activeTab, setActiveTab] = useState<'evaluations' | 'metrics' | 'context'>('evaluations')
  const [evaluations, setEvaluations] = useState<EvaluationRecord[]>([])
  const [metrics, setMetrics] = useState<AggregateMetrics | null>(null)
  const [selectedType, setSelectedType] = useState<string>('DEMAND_FORECAST')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (isOpen) {
      setLoading(true)
      const token = 'Bearer dev_admin_token'
      const headers = { 'Authorization': token }

      Promise.all([
        fetch('http://localhost:8000/api/v3/learning/evaluations?limit=50', { headers })
          .then(res => res.ok ? res.json() : [])
          .catch(() => []),
        fetch(`http://localhost:8000/api/v3/learning/metrics?prediction_type=${selectedType}`, { headers })
          .then(res => res.ok ? res.json() : null)
          .catch(() => null),
      ]).then(([evalData, metricsData]) => {
        setEvaluations(evalData || [])
        setMetrics(metricsData)
        setLoading(false)
      })
    }
  }, [isOpen, selectedType])

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4">
      <div className="relative w-full max-w-5xl max-h-[90vh] bg-[#0c0d0e] border border-zinc-800 rounded-xl flex flex-col shadow-2xl overflow-hidden font-mono text-xs">
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-800 bg-[#121315]">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-emerald-950/40 border border-emerald-500/30 text-emerald-400">
              <Scale className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-zinc-100 tracking-wide uppercase">
                  Closed-Loop Outcome Learning & Prediction Evaluation
                </h2>
                <span className="px-2 py-0.5 rounded-full bg-emerald-900/40 border border-emerald-700/50 text-[10px] text-emerald-400">
                  Prompt 39 Governed
                </span>
              </div>
              <p className="text-[11px] text-zinc-400">
                Deterministic comparison of predictions against verified outcomes — zero autonomous execution
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg border border-zinc-700/50 hover:bg-zinc-800 text-zinc-400 hover:text-zinc-100 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Notice Banner */}
        <div className="px-6 py-2 bg-zinc-900/60 border-b border-zinc-800 flex items-center gap-2 text-zinc-400 text-[11px]">
          <Info className="w-4 h-4 text-cyan-400 shrink-0" />
          <span>
            Governed Operational Feedback Layer: Compares historical expectations against verified observations to establish trustworthy decision-support context.
          </span>
        </div>

        {/* Tab Controls & Filter */}
        <div className="flex items-center justify-between px-6 py-3 border-b border-zinc-800/80 bg-[#0f1012]">
          <div className="flex gap-2">
            <button
              onClick={() => setActiveTab('evaluations')}
              className={`px-3 py-1.5 rounded-md border text-xs transition-colors ${
                activeTab === 'evaluations'
                  ? 'bg-zinc-800 border-zinc-600 text-zinc-100 font-semibold'
                  : 'bg-zinc-900/40 border-zinc-800 text-zinc-400 hover:text-zinc-200'
              }`}
            >
              Evaluations Ledger ({evaluations.length})
            </button>
            <button
              onClick={() => setActiveTab('metrics')}
              className={`px-3 py-1.5 rounded-md border text-xs transition-colors ${
                activeTab === 'metrics'
                  ? 'bg-zinc-800 border-zinc-600 text-zinc-100 font-semibold'
                  : 'bg-zinc-900/40 border-zinc-800 text-zinc-400 hover:text-zinc-200'
              }`}
            >
              Aggregate Accuracy & Bias Metrics
            </button>
            <button
              onClick={() => setActiveTab('context')}
              className={`px-3 py-1.5 rounded-md border text-xs transition-colors ${
                activeTab === 'context'
                  ? 'bg-zinc-800 border-zinc-600 text-zinc-100 font-semibold'
                  : 'bg-zinc-900/40 border-zinc-800 text-zinc-400 hover:text-zinc-200'
              }`}
            >
              Governed Decision Context
            </button>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-zinc-400">Domain:</span>
            <select
              value={selectedType}
              onChange={(e) => setSelectedType(e.target.value)}
              className="bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-zinc-200 focus:outline-none focus:border-cyan-500"
            >
              <option value="DEMAND_FORECAST">DEMAND_FORECAST</option>
              <option value="RECOVERY_DURATION">RECOVERY_DURATION</option>
              <option value="MAINTENANCE_RISK">MAINTENANCE_RISK</option>
              <option value="OPERATIONAL_COST">OPERATIONAL_COST</option>
              <option value="MISSION_CRITERION">MISSION_CRITERION</option>
            </select>
          </div>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {loading ? (
            <div className="py-16 text-center text-zinc-500">
              <div className="inline-block animate-spin w-6 h-6 border-2 border-cyan-500 border-t-transparent rounded-full mb-2" />
              <p>Loading governed outcome evaluations...</p>
            </div>
          ) : activeTab === 'evaluations' ? (
            evaluations.length === 0 ? (
              <div className="py-16 text-center text-zinc-500 border border-dashed border-zinc-800 rounded-lg">
                <Database className="w-8 h-8 mx-auto mb-2 text-zinc-600" />
                <p>No outcome evaluations recorded in this workspace scope yet.</p>
                <p className="text-[10px] text-zinc-600 mt-1">
                  Evaluations are created when verified observations are paired with prior expectations.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {evaluations.map((ev) => (
                  <div
                    key={ev.evaluation_id}
                    className="p-4 rounded-lg bg-zinc-900/50 border border-zinc-800 hover:border-zinc-700 transition-colors"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 font-semibold text-[10px]">
                          {ev.prediction_type}
                        </span>
                        <span className="text-zinc-400 font-mono text-[11px]">
                          Target: <span className="text-zinc-200">{ev.target_reference}</span>
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        {ev.eligible_for_learning ? (
                          <span className="flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-950/60 border border-emerald-700/60 text-emerald-400 text-[10px]">
                            <CheckCircle2 className="w-3 h-3" /> ELIGIBLE FOR FUTURE LEARNING
                          </span>
                        ) : (
                          <span className="flex items-center gap-1 px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-400 text-[10px]" title={ev.learning_ineligibility_reason || 'Ineligible'}>
                            <AlertTriangle className="w-3 h-3 text-amber-500" /> EXCLUDED FROM LEARNING
                          </span>
                        )}
                        <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 text-[10px]">
                          {ev.data_mode}
                        </span>
                      </div>
                    </div>

                    {/* Comparison Box */}
                    <div className="grid grid-cols-4 gap-3 my-3 p-3 bg-black/40 rounded border border-zinc-800/80">
                      <div>
                        <div className="text-[10px] text-zinc-500 uppercase">PREDICTED EXPECTATION</div>
                        <div className="text-sm font-semibold text-cyan-400 mt-0.5">
                          {String(ev.predicted_value)} {ev.unit || ''}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-zinc-500 uppercase">OBSERVED OUTCOME</div>
                        <div className="text-sm font-semibold text-emerald-400 mt-0.5">
                          {String(ev.observed_value)} {ev.unit || ''}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-zinc-500 uppercase">ABSOLUTE ERROR</div>
                        <div className="text-sm font-semibold text-zinc-200 mt-0.5">
                          {ev.absolute_error !== undefined && ev.absolute_error !== null
                            ? ev.absolute_error
                            : 'N/A'}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-zinc-500 uppercase">DIRECTIONAL BIAS</div>
                        <div className="flex items-center gap-1 text-sm font-semibold mt-0.5 text-zinc-200">
                          {ev.directional_bias === 'OVER_PREDICTED' && (
                            <span className="text-amber-400 flex items-center gap-1">
                              <TrendingUp className="w-3.5 h-3.5" /> OVER_PREDICTED
                            </span>
                          )}
                          {ev.directional_bias === 'UNDER_PREDICTED' && (
                            <span className="text-cyan-400 flex items-center gap-1">
                              <TrendingDown className="w-3.5 h-3.5" /> UNDER_PREDICTED
                            </span>
                          )}
                          {ev.directional_bias === 'MATCHED' && (
                            <span className="text-emerald-400 flex items-center gap-1">
                              <CheckCircle2 className="w-3.5 h-3.5" /> MATCHED
                            </span>
                          )}
                          {!ev.directional_bias && <span className="text-zinc-500">N/A</span>}
                        </div>
                      </div>
                    </div>

                    {/* Footer Details */}
                    <div className="flex items-center justify-between text-[10px] text-zinc-500">
                      <div className="flex items-center gap-4">
                        <span>Evaluation ID: <span className="font-mono text-zinc-400">{ev.evaluation_id}</span></span>
                        <span>Plant: <span className="text-zinc-400">{ev.plant_id}</span></span>
                        {ev.verification_reference && (
                          <span>Verification Ref: <span className="text-zinc-400">{ev.verification_reference}</span></span>
                        )}
                      </div>
                      <div className="flex items-center gap-1">
                        <Clock className="w-3 h-3 text-zinc-500" />
                        <span>{ev.evaluated_at}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )
          ) : activeTab === 'metrics' ? (
            metrics ? (
              <div className="space-y-4">
                <div className="grid grid-cols-4 gap-4">
                  <div className="p-4 bg-zinc-900/60 border border-zinc-800 rounded-lg">
                    <div className="text-[10px] text-zinc-500 uppercase">Eligible Samples</div>
                    <div className="text-2xl font-bold text-zinc-100 mt-1">
                      {metrics.eligible_sample_count}
                    </div>
                    <div className="text-[10px] text-zinc-400 mt-1">
                      Status: <span className={metrics.sample_status === 'SUFFICIENT_DATA' ? 'text-emerald-400 font-semibold' : 'text-amber-400 font-semibold'}>
                        {metrics.sample_status}
                      </span>
                    </div>
                  </div>

                  <div className="p-4 bg-zinc-900/60 border border-zinc-800 rounded-lg">
                    <div className="text-[10px] text-zinc-500 uppercase">Mean Absolute Error (MAE)</div>
                    <div className="text-2xl font-bold text-cyan-400 mt-1">
                      {metrics.mean_absolute_error !== null && metrics.mean_absolute_error !== undefined
                        ? `${metrics.mean_absolute_error} ${metrics.unit || ''}`
                        : 'N/A'}
                    </div>
                    <div className="text-[10px] text-zinc-400 mt-1">
                      RMSE: {metrics.root_mean_squared_error !== null && metrics.root_mean_squared_error !== undefined ? metrics.root_mean_squared_error : 'N/A'}
                    </div>
                  </div>

                  <div className="p-4 bg-zinc-900/60 border border-zinc-800 rounded-lg">
                    <div className="text-[10px] text-zinc-500 uppercase">Mean Abs % Error (MAPE)</div>
                    <div className="text-2xl font-bold text-zinc-100 mt-1">
                      {metrics.mean_absolute_percentage_error !== null && metrics.mean_absolute_percentage_error !== undefined
                        ? `${metrics.mean_absolute_percentage_error}%`
                        : 'N/A'}
                    </div>
                    <div className="text-[10px] text-zinc-400 mt-1">
                      Signed Bias: {metrics.signed_mean_error !== null && metrics.signed_mean_error !== undefined ? metrics.signed_mean_error : 'N/A'}
                    </div>
                  </div>

                  <div className="p-4 bg-zinc-900/60 border border-zinc-800 rounded-lg">
                    <div className="text-[10px] text-zinc-500 uppercase">Exact Match Rate</div>
                    <div className="text-2xl font-bold text-emerald-400 mt-1">
                      {metrics.exact_match_rate !== null && metrics.exact_match_rate !== undefined
                        ? `${(metrics.exact_match_rate * 100).toFixed(1)}%`
                        : 'N/A'}
                    </div>
                    <div className="text-[10px] text-zinc-400 mt-1">
                      Exact count: {metrics.exact_matched_count}
                    </div>
                  </div>
                </div>

                {/* Bias Breakdown */}
                <div className="p-4 bg-zinc-900/40 border border-zinc-800 rounded-lg">
                  <div className="text-xs font-semibold text-zinc-200 mb-2">Directional Prediction Distribution</div>
                  <div className="grid grid-cols-3 gap-3">
                    <div className="p-3 bg-black/40 rounded border border-zinc-800">
                      <div className="text-[10px] text-zinc-500">Over-Predicted Count</div>
                      <div className="text-lg font-bold text-amber-400">{metrics.over_predicted_count}</div>
                    </div>
                    <div className="p-3 bg-black/40 rounded border border-zinc-800">
                      <div className="text-[10px] text-zinc-500">Under-Predicted Count</div>
                      <div className="text-lg font-bold text-cyan-400">{metrics.under_predicted_count}</div>
                    </div>
                    <div className="p-3 bg-black/40 rounded border border-zinc-800">
                      <div className="text-[10px] text-zinc-500">Matched Count</div>
                      <div className="text-lg font-bold text-emerald-400">{metrics.exact_matched_count}</div>
                    </div>
                  </div>
                </div>

                {/* Exclusions Box */}
                <div className="p-4 bg-zinc-900/40 border border-zinc-800 rounded-lg text-zinc-400">
                  <div className="text-xs font-semibold text-zinc-200 mb-2">Exclusions & Hygiene</div>
                  <div className="flex gap-6 text-[11px]">
                    <span>Total Evaluations: <strong className="text-zinc-200">{metrics.total_evaluations}</strong></span>
                    <span>Excluded: <strong className="text-amber-400">{metrics.excluded_evaluations}</strong></span>
                    <span>Unverified: <strong className="text-zinc-300">{metrics.unverified_count}</strong></span>
                    <span>Deferred: <strong className="text-zinc-300">{metrics.deferred_count}</strong></span>
                    <span>Rejected: <strong className="text-zinc-300">{metrics.rejected_count}</strong></span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="py-16 text-center text-zinc-500 border border-dashed border-zinc-800 rounded-lg">
                <Scale className="w-8 h-8 mx-auto mb-2 text-zinc-600" />
                <p>No aggregate metrics available for domain '{selectedType}'.</p>
              </div>
            )
          ) : (
            /* Context Tab */
            <div className="space-y-4">
              <div className="p-4 bg-zinc-900/60 border border-zinc-800 rounded-lg">
                <div className="flex items-center gap-2 text-xs font-semibold text-zinc-200 mb-2">
                  <BrainCircuit className="w-4 h-4 text-cyan-400" />
                  Governed Decision-Support Context for Future Estimators
                </div>
                <p className="text-[11px] text-zinc-400 leading-relaxed">
                  Historical error and bias distributions are exposed as read-only evidence to future decision-support processes (e.g. demand forecasting, recovery duration estimators). Future models can consult this evidence to adjust confidence intervals without autonomously rewriting policy rules or changing weights.
                </p>
              </div>

              <div className="p-4 bg-zinc-900/40 border border-zinc-800 rounded-lg">
                <div className="text-xs font-semibold text-zinc-200 mb-2">Mandatory Governance Invariants</div>
                <ul className="space-y-1.5 text-[11px] text-zinc-400 list-disc list-inside">
                  <li>Zero online reinforcement learning against live production machines.</li>
                  <li>Zero autonomous PLC/SCADA setpoint changes or physical actuators.</li>
                  <li>Unverified or diagnostic observations can never contaminate learning metrics.</li>
                  <li>Sample counts below minimum threshold ({metrics?.min_sample_threshold || 5}) report INSUFFICIENT_DATA honestly.</li>
                  <li>Evaluation results are append-only; historical error records cannot be edited.</li>
                </ul>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-zinc-800 bg-[#121315] flex items-center justify-between text-zinc-500 text-[10px]">
          <span>SageCommand V3 Closed-Loop Learning Foundation • Read-Only Decision Evidence</span>
          <span>Policy v1.0.0 • SQLite WAL Scoped</span>
        </div>
      </div>
    </div>
  )
}
