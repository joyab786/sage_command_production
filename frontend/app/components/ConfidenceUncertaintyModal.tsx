"use client";

import React, { useState, useEffect } from "react";
import {
  ShieldAlert,
  HelpCircle,
  Activity,
  Layers,
  AlertTriangle,
  Clock,
  Database,
  BarChart2,
  FileText,
  X,
  RefreshCw,
  Info,
  CheckCircle2,
  Sliders,
  TrendingDown,
  Sparkles,
} from "lucide-react";
import {
  assessConfidence,
  getConfidenceAssessment,
  listConfidenceAssessments,
} from "../../lib/api";

interface ConfidenceUncertaintyModalProps {
  isOpen: boolean;
  onClose: () => void;
  targetId?: string;
  targetType?: string;
  tenantId?: string;
  workspaceId?: string;
  plantId?: string;
}

export default function ConfidenceUncertaintyModal({
  isOpen,
  onClose,
  targetId = "dec_auto_001",
  targetType = "DECISION_ENGINE",
  tenantId = "tenant_default",
  workspaceId = "workspace_primary",
  plantId = "PLANT-01",
}: ConfidenceUncertaintyModalProps) {
  const [activeTab, setActiveTab] = useState<
    "overview" | "dimensions" | "uncertainty" | "ranges" | "evidence" | "limitations" | "history"
  >("overview");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [assessment, setAssessment] = useState<any | null>(null);
  const [historyList, setHistoryList] = useState<any[]>([]);

  // Form input states
  const [selectedTargetType, setSelectedTargetType] = useState(targetType);
  const [selectedTargetId, setSelectedTargetId] = useState(targetId);

  useEffect(() => {
    if (isOpen) {
      loadAssessment();
      loadHistory();
    }
  }, [isOpen]);

  async function loadAssessment() {
    setLoading(true);
    setError(null);
    try {
      const res = await assessConfidence({
        target_type: selectedTargetType,
        target_id: selectedTargetId,
        tenant_id: tenantId,
        workspace_id: workspaceId,
        plant_id: plantId,
        include_ranges: true,
        include_sensitivities: true,
      });
      setAssessment(res);
    } catch (err: any) {
      setError(err?.message || "Failed to evaluate confidence and uncertainty.");
    } finally {
      setLoading(false);
    }
  }

  async function loadHistory() {
    try {
      const res = await listConfidenceAssessments(15, 0, workspaceId, plantId, selectedTargetType);
      if (res && res.items) {
        setHistoryList(res.items);
      }
    } catch {
      // Non-blocking history load
    }
  }

  if (!isOpen) return null;

  const confScore = assessment?.confidence?.aggregate_score;
  const confStatus = assessment?.confidence?.status || "NOT_ASSESSABLE";

  // Color mapping for confidence status
  const getStatusColor = (status: string) => {
    switch (status) {
      case "HIGH_CONFIDENCE":
        return "text-emerald-400 bg-emerald-500/10 border-emerald-500/30";
      case "MODERATE_CONFIDENCE":
        return "text-amber-400 bg-amber-500/10 border-amber-500/30";
      case "LOW_CONFIDENCE":
        return "text-orange-400 bg-orange-500/10 border-orange-500/30";
      case "VERY_LOW_CONFIDENCE":
        return "text-rose-400 bg-rose-500/10 border-rose-500/30";
      default:
        return "text-slate-400 bg-slate-500/10 border-slate-500/30";
    }
  };

  const getProvenanceBadge = (prov: string) => {
    switch (prov) {
      case "OBSERVED":
        return "text-emerald-300 bg-emerald-500/10 border-emerald-500/30";
      case "DERIVED":
        return "text-sky-300 bg-sky-500/10 border-sky-500/30";
      case "FORECAST":
        return "text-purple-300 bg-purple-500/10 border-purple-500/30";
      case "SIMULATED":
        return "text-cyan-300 bg-cyan-500/10 border-cyan-500/30";
      case "ESTIMATED":
        return "text-amber-300 bg-amber-500/10 border-amber-500/30";
      default:
        return "text-rose-300 bg-rose-500/10 border-rose-500/30";
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
      <div className="flex flex-col w-full max-w-6xl max-h-[92vh] overflow-hidden rounded-xl border border-indigo-500/30 bg-slate-950/95 shadow-2xl text-slate-100">
        
        {/* --- MODAL HEADER --- */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-indigo-500/20 bg-slate-900/60">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-indigo-500/10 border border-indigo-500/30">
              <ShieldAlert className="w-5 h-5 text-indigo-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold tracking-wide text-indigo-200">
                Confidence & Uncertainty Intelligence Inspector
              </h2>
              <p className="text-xs text-slate-400">
                Deterministic evidential reliability and decomposed uncertainty analysis
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={loadAssessment}
              disabled={loading}
              className="px-3 py-1.5 text-xs font-medium rounded-md bg-indigo-500/20 border border-indigo-500/40 text-indigo-300 hover:bg-indigo-500/30 flex items-center gap-1.5 transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
              Re-Assess
            </button>
            <button
              onClick={onClose}
              className="p-1.5 text-slate-400 hover:text-white rounded-md hover:bg-slate-800/80 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* --- MANDATORY ANALYTICAL-ONLY NOTICE --- */}
        <div className="px-6 py-2 bg-amber-500/10 border-b border-amber-500/20 text-amber-300/90 text-xs font-mono flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />
            <span>CONFIDENCE AND UNCERTAINTY ANALYSIS ONLY — NOT AUTHORIZED AND NOT EXECUTED</span>
          </div>
          <span className="text-[10px] text-amber-400/70">READ-ONLY ANALYTICAL INTELLIGENCE</span>
        </div>

        {/* --- TARGET SELECTION BAR --- */}
        <div className="flex items-center gap-4 px-6 py-3 border-b border-slate-800 bg-slate-900/30 text-xs">
          <span className="text-slate-400 font-medium">Evaluation Target:</span>
          <select
            value={selectedTargetType}
            onChange={(e) => setSelectedTargetType(e.target.value)}
            className="px-2.5 py-1 rounded bg-slate-800/80 border border-slate-700 text-slate-200"
          >
            <option value="DECISION_ENGINE">Decision Engine</option>
            <option value="OPTIMIZATION">Optimization Engine</option>
            <option value="WHAT_IF_SIMULATION">What-If Simulation</option>
            <option value="SENSOR_FUSION">Sensor Fusion</option>
            <option value="PREDICTIVE_MAINTENANCE">Predictive Maintenance</option>
            <option value="DEMAND_FORECASTING">Demand Forecasting</option>
            <option value="SUPPLIER_RISK">Supplier Risk</option>
            <option value="FINANCIAL_IMPACT">Financial Impact</option>
            <option value="SUSTAINABILITY">Sustainability</option>
            <option value="ANOMALY_DETECTION">Anomaly Detection</option>
          </select>
          <input
            type="text"
            value={selectedTargetId}
            onChange={(e) => setSelectedTargetId(e.target.value)}
            placeholder="Target Record ID"
            className="px-2.5 py-1 rounded bg-slate-800/80 border border-slate-700 text-slate-200 font-mono text-xs w-48"
          />
          <button
            onClick={loadAssessment}
            className="px-3 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs transition-colors"
          >
            Evaluate
          </button>
        </div>

        {/* --- TAB NAVIGATION --- */}
        <div className="flex items-center gap-1 px-6 border-b border-slate-800 bg-slate-950">
          {[
            { id: "overview", label: "Overview", icon: Activity },
            { id: "dimensions", label: "10 Dimensions", icon: Sliders },
            { id: "uncertainty", label: "Decomposition", icon: HelpCircle },
            { id: "ranges", label: "Intervals & Sensitivity", icon: BarChart2 },
            { id: "evidence", label: "Evidence Corroboration", icon: Database },
            { id: "limitations", label: "Deficiencies & Gaps", icon: AlertTriangle },
            { id: "history", label: "Audit & History", icon: Clock },
          ].map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`flex items-center gap-2 px-4 py-3 text-xs font-medium border-b-2 transition-all ${
                  isActive
                    ? "border-indigo-400 text-indigo-300 bg-indigo-500/5"
                    : "border-transparent text-slate-400 hover:text-slate-200 hover:border-slate-700"
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* --- MAIN TAB CONTENT --- */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {error && (
            <div className="p-4 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-3">
              <AlertTriangle className="w-5 h-5 flex-shrink-0 text-rose-400" />
              <div>
                <p className="font-semibold">Evaluation Error</p>
                <p>{error}</p>
              </div>
            </div>
          )}

          {/* === TAB 1: OVERVIEW === */}
          {activeTab === "overview" && (
            <div className="space-y-6">
              {/* Top Banner Stats */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/50">
                  <span className="text-xs text-slate-400">Aggregate Confidence</span>
                  <div className="flex items-baseline gap-2 mt-1">
                    <span className="text-2xl font-bold font-mono text-white">
                      {confScore !== null && confScore !== undefined ? `${(confScore * 100).toFixed(1)}%` : "N/A"}
                    </span>
                    <span className={`text-[11px] px-2 py-0.5 rounded border ${getStatusColor(confStatus)}`}>
                      {confStatus}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-500 mt-2">Analytical evidential support index</p>
                </div>

                <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/50">
                  <span className="text-xs text-slate-400">Predominant Uncertainty</span>
                  <div className="text-lg font-semibold text-purple-300 mt-1">
                    {assessment?.uncertainty?.decomposition?.predominant_type || "UNKNOWN"}
                  </div>
                  <p className="text-[11px] text-slate-500 mt-2">
                    {assessment?.uncertainty?.decomposition?.total_components_count || 0} decomposed components
                  </p>
                </div>

                <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/50">
                  <span className="text-xs text-slate-400">Supporting Evidence</span>
                  <div className="text-2xl font-bold font-mono text-sky-400 mt-1">
                    {assessment?.supporting_evidence?.length || 0} items
                  </div>
                  <p className="text-[11px] text-slate-500 mt-2">Corroborating analytical inputs</p>
                </div>

                <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/50">
                  <span className="text-xs text-slate-400">Deficiencies / Caps</span>
                  <div className="text-2xl font-bold font-mono text-amber-400 mt-1">
                    {assessment?.confidence?.blocking_deficiencies?.length || 0}
                  </div>
                  <p className="text-[11px] text-slate-500 mt-2">Enforced score ceiling factors</p>
                </div>
              </div>

              {/* Detailed Interpretation Card */}
              <div className="p-5 rounded-xl border border-indigo-500/20 bg-indigo-950/10">
                <h3 className="text-sm font-semibold text-indigo-300 flex items-center gap-2">
                  <Info className="w-4 h-4 text-indigo-400" />
                  Evidential Support Interpretation
                </h3>
                <p className="text-xs text-slate-300 mt-2 leading-relaxed">
                  {assessment?.confidence?.interpretations || "No interpretation available."}
                </p>
                <div className="mt-4 pt-3 border-t border-indigo-500/20 flex flex-wrap items-center gap-6 text-xs text-slate-400 font-mono">
                  <span>Target: {assessment?.target_type} ({assessment?.target_id})</span>
                  <span>Assessment Time: {assessment?.assessment_timestamp}</span>
                  <span>Algorithm: {assessment?.method?.version || "1.0.0"}</span>
                </div>
              </div>

              {/* Blocking Deficiencies Warning */}
              {assessment?.confidence?.blocking_deficiencies?.length > 0 && (
                <div className="p-4 rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-300 text-xs space-y-2">
                  <div className="flex items-center gap-2 font-semibold">
                    <AlertTriangle className="w-4 h-4 text-amber-400" />
                    Enforced Score Caps (Deficiency Rule Applied):
                  </div>
                  <ul className="list-disc list-inside space-y-1 pl-2 text-slate-300">
                    {assessment.confidence.blocking_deficiencies.map((b: string, i: number) => (
                      <li key={i}><span className="font-mono text-amber-400">{b}</span> — Prevented high scores from masking critical defects.</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* === TAB 2: 10 CONFIDENCE DIMENSIONS === */}
          {activeTab === "dimensions" && (
            <div className="space-y-4">
              <div className="text-xs text-slate-400">
                Multi-dimensional decomposition isolates 10 independent indicators rather than collapsing quality into an opaque number.
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {(assessment?.confidence?.dimensions || []).map((dim: any, idx: number) => (
                  <div key={idx} className="p-4 rounded-xl border border-slate-800 bg-slate-900/50 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-indigo-200">
                        {dim.dimension_type.replace(/_/g, " ")}
                      </span>
                      <span className={`text-[10px] px-2 py-0.5 rounded border ${dim.score !== null ? "text-slate-200 border-slate-700 bg-slate-800" : "text-slate-400 border-slate-800 bg-slate-900"}`}>
                        Weight: {dim.weight}
                      </span>
                    </div>

                    <div className="space-y-1">
                      <div className="flex justify-between text-xs font-mono">
                        <span className="text-slate-400">Score</span>
                        <span className="text-white font-bold">
                          {dim.score !== null ? `${(dim.score * 100).toFixed(1)}%` : "NOT ASSESSABLE"}
                        </span>
                      </div>
                      <div className="w-full h-1.5 rounded-full bg-slate-800 overflow-hidden">
                        <div
                          className={`h-full rounded-full ${
                            dim.score === null
                              ? "bg-slate-700 w-0"
                              : dim.score >= 0.75
                              ? "bg-emerald-400"
                              : dim.score >= 0.5
                              ? "bg-amber-400"
                              : "bg-rose-400"
                          }`}
                          style={{ width: `${(dim.score || 0) * 100}%` }}
                        />
                      </div>
                    </div>

                    <p className="text-[11px] text-slate-300 leading-normal">{dim.explanation}</p>

                    {dim.deficiencies && dim.deficiencies.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {dim.deficiencies.map((d: string, di: number) => (
                          <span key={di} className="text-[9px] px-1.5 py-0.5 rounded bg-rose-500/10 border border-rose-500/20 text-rose-300 font-mono">
                            {d}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* === TAB 3: UNCERTAINTY DECOMPOSITION === */}
          {activeTab === "uncertainty" && (
            <div className="space-y-6">
              <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/40 text-xs text-slate-300">
                <p className="font-semibold text-slate-200">Decomposition Overview</p>
                <p className="mt-1">{assessment?.uncertainty?.decomposition?.summary || "No decomposition computed."}</p>
              </div>

              {/* Aleatoric vs Epistemic Split */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Epistemic */}
                <div className="p-5 rounded-xl border border-purple-500/20 bg-purple-950/10 space-y-3">
                  <div className="flex items-center gap-2">
                    <HelpCircle className="w-4 h-4 text-purple-400" />
                    <h3 className="text-xs font-semibold text-purple-200">Epistemic Uncertainty (Reducible by Evidence)</h3>
                  </div>
                  <p className="text-[11px] text-slate-400 leading-normal">
                    Arises from knowledge limitations, sample sparsity, unverified assumptions, and conflicting observations.
                  </p>

                  <div className="space-y-2 pt-2">
                    {(assessment?.uncertainty?.decomposition?.epistemic_components || []).map((c: any, i: number) => (
                      <div key={i} className="p-3 rounded-lg border border-purple-500/20 bg-slate-900/60 text-xs space-y-1">
                        <div className="flex items-center justify-between">
                          <span className="font-mono text-purple-300 font-medium">{c.uncertainty_type}</span>
                          <span className="text-[10px] text-slate-400 uppercase">{c.severity}</span>
                        </div>
                        <p className="text-[11px] text-slate-300">{c.description}</p>
                      </div>
                    ))}
                    {(!assessment?.uncertainty?.decomposition?.epistemic_components || assessment.uncertainty.decomposition.epistemic_components.length === 0) && (
                      <p className="text-[11px] text-slate-500 italic">No significant epistemic components detected.</p>
                    )}
                  </div>
                </div>

                {/* Aleatoric */}
                <div className="p-5 rounded-xl border border-cyan-500/20 bg-cyan-950/10 space-y-3">
                  <div className="flex items-center gap-2">
                    <TrendingDown className="w-4 h-4 text-cyan-400" />
                    <h3 className="text-xs font-semibold text-cyan-200">Aleatoric Uncertainty (Inherent Stochasticity)</h3>
                  </div>
                  <p className="text-[11px] text-slate-400 leading-normal">
                    Inherent process variability, thermal noise, and operational stochasticity that cannot be reduced by collecting more samples.
                  </p>

                  <div className="space-y-2 pt-2">
                    {(assessment?.uncertainty?.decomposition?.aleatoric_components || []).map((c: any, i: number) => (
                      <div key={i} className="p-3 rounded-lg border border-cyan-500/20 bg-slate-900/60 text-xs space-y-1">
                        <div className="flex items-center justify-between">
                          <span className="font-mono text-cyan-300 font-medium">{c.uncertainty_type}</span>
                          <span className="text-[10px] text-slate-400 uppercase">{c.severity}</span>
                        </div>
                        <p className="text-[11px] text-slate-300">{c.description}</p>
                      </div>
                    ))}
                    {(!assessment?.uncertainty?.decomposition?.aleatoric_components || assessment.uncertainty.decomposition.aleatoric_components.length === 0) && (
                      <p className="text-[11px] text-slate-500 italic">No significant aleatoric variability components detected.</p>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* === TAB 4: RANGES & SENSITIVITIES === */}
          {activeTab === "ranges" && (
            <div className="space-y-6">
              {/* Quantified Ranges */}
              <div className="space-y-3">
                <h3 className="text-xs font-semibold text-slate-300">Quantified Numerical Intervals & Bounds</h3>
                {assessment?.uncertainty?.primary_ranges && assessment.uncertainty.primary_ranges.length > 0 ? (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {assessment.uncertainty.primary_ranges.map((r: any, i: number) => (
                      <div key={i} className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 space-y-2">
                        <div className="flex items-center justify-between text-xs">
                          <span className="font-mono text-indigo-300 font-medium">{r.interval_type}</span>
                          <span className="text-[10px] text-slate-400 font-mono">Unit: {r.unit}</span>
                        </div>
                        <div className="flex items-baseline gap-3 text-lg font-mono font-bold text-white">
                          <span>[{r.lower_bound}</span>
                          <span className="text-slate-500 font-normal">to</span>
                          <span>{r.upper_bound}]</span>
                          {r.confidence_level && (
                            <span className="text-xs font-normal text-emerald-400">({(r.confidence_level * 100).toFixed(0)}% coverage)</span>
                          )}
                        </div>
                        <p className="text-[11px] text-slate-400">{r.description || r.distribution_assumptions}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/40 text-xs text-slate-400 italic">
                    No validated quantitative intervals mathematically justified. Qualitative uncertainty maintained to prevent false precision.
                  </div>
                )}
              </div>

              {/* Parameter Sensitivities */}
              <div className="space-y-3 pt-4 border-t border-slate-800">
                <h3 className="text-xs font-semibold text-slate-300">Parameter Sensitivity Analysis</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {(assessment?.uncertainty?.sensitivities || []).map((s: any, i: number) => (
                    <div key={i} className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 space-y-2 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-slate-200 font-medium">{s.parameter_name}</span>
                        <span className="font-mono text-indigo-400 font-bold">Index: {s.sensitivity_index}</span>
                      </div>
                      <p className="text-[11px] text-slate-400">{s.notes}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* === TAB 5: EVIDENCE CORROBORATION === */}
          {activeTab === "evidence" && (
            <div className="space-y-6">
              <div className="space-y-3">
                <h3 className="text-xs font-semibold text-slate-300">Supporting Corroborating Evidence ({assessment?.supporting_evidence?.length || 0})</h3>
                <div className="space-y-2">
                  {(assessment?.supporting_evidence || []).map((ev: any, idx: number) => (
                    <div key={idx} className="p-3 rounded-lg border border-slate-800 bg-slate-900/50 flex items-center justify-between text-xs">
                      <div className="flex items-center gap-3">
                        <Database className="w-4 h-4 text-sky-400 flex-shrink-0" />
                        <div>
                          <span className="font-mono font-medium text-white">{ev.evidence_id}</span>
                          <div className="flex items-center gap-2 mt-0.5 text-[10px] text-slate-400">
                            <span>Source: {ev.source_type} ({ev.source_record_id})</span>
                            <span>•</span>
                            <span>Quality: {ev.quality_score}</span>
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={`text-[10px] px-2 py-0.5 rounded border font-mono ${getProvenanceBadge(ev.provenance)}`}>
                          {ev.provenance}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {assessment?.conflicting_evidence?.length > 0 && (
                <div className="space-y-3 pt-4 border-t border-slate-800">
                  <h3 className="text-xs font-semibold text-rose-300">Conflicting Evidence ({assessment.conflicting_evidence.length})</h3>
                  <div className="space-y-2">
                    {assessment.conflicting_evidence.map((c: any, idx: number) => (
                      <div key={idx} className="p-3 rounded-lg border border-rose-500/20 bg-rose-500/5 text-xs text-rose-300 space-y-1">
                        <div className="flex items-center justify-between font-mono">
                          <span>{c.evidence_id}</span>
                          <span className="text-[10px] text-rose-400">CONFLICTING</span>
                        </div>
                        <p className="text-[11px] text-slate-300">{c.notes}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* === TAB 6: LIMITATIONS & DEFICIENCIES === */}
          {activeTab === "limitations" && (
            <div className="space-y-4">
              <h3 className="text-xs font-semibold text-slate-300">Explicit Assessment Limitations</h3>
              <div className="space-y-3">
                {(assessment?.limitations || []).map((lim: any, idx: number) => (
                  <div key={idx} className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 text-xs space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-indigo-300 font-semibold">{lim.code}</span>
                      <span className={`text-[10px] px-2 py-0.5 rounded border ${lim.severity === "BLOCKING" ? "text-rose-400 bg-rose-500/10 border-rose-500/30" : "text-amber-400 bg-amber-500/10 border-amber-500/30"}`}>
                        {lim.severity}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-300 leading-normal">{lim.description}</p>
                    {lim.mitigation && (
                      <p className="text-[10px] text-slate-400 border-t border-slate-800 pt-2 font-mono">
                        Mitigation: {lim.mitigation}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* === TAB 7: AUDIT & HISTORY === */}
          {activeTab === "history" && (
            <div className="space-y-6">
              {/* Fingerprint Card */}
              <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/50 space-y-2">
                <span className="text-xs font-semibold text-indigo-300">Deterministic Fingerprint (SHA-256)</span>
                <p className="text-xs text-slate-400 leading-relaxed">
                  Cryptographic digest of material inputs, dimensions, and source versions guaranteeing reproducibility.
                </p>
                <div className="p-2.5 rounded bg-slate-950 border border-slate-800 font-mono text-[11px] text-indigo-300 select-all">
                  {assessment?.fingerprint || "N/A"}
                </div>
              </div>

              {/* Historical Assessments */}
              <div className="space-y-3">
                <h3 className="text-xs font-semibold text-slate-300">Historical Assessments for Target</h3>
                <div className="space-y-2">
                  {historyList.map((h: any, idx: number) => (
                    <div key={idx} className="p-3 rounded-lg border border-slate-800 bg-slate-900/40 flex items-center justify-between text-xs">
                      <div>
                        <span className="font-mono text-white">{h.assessment_id}</span>
                        <div className="text-[10px] text-slate-400 mt-0.5">
                          {h.assessment_timestamp} • {h.predominant_uncertainty}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-white font-bold">
                          {h.aggregate_confidence !== null ? `${(h.aggregate_confidence * 100).toFixed(1)}%` : "N/A"}
                        </span>
                        <span className={`text-[10px] px-2 py-0.5 rounded border ${getStatusColor(h.confidence_status)}`}>
                          {h.confidence_status}
                        </span>
                      </div>
                    </div>
                  ))}
                  {historyList.length === 0 && (
                    <p className="text-xs text-slate-500 italic">No prior assessment history found.</p>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* --- MODAL FOOTER --- */}
        <div className="px-6 py-3 border-t border-slate-800 bg-slate-900/60 flex items-center justify-between text-xs text-slate-400">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            <span>Deterministic Engine Active</span>
            <span>•</span>
            <span>Tenant: {tenantId}</span>
            <span>•</span>
            <span>Scope: Read-Only Analytical</span>
          </div>

          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium transition-colors"
          >
            Close Inspector
          </button>
        </div>

      </div>
    </div>
  );
}
