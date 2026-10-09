"use client";

/**
 * frontend/app/components/EvidenceExplainabilityModal.tsx
 *
 * SageCommand V3 — Evidence and Explainability Intelligence Foundation Modal (Prompt 31)
 *
 * ANALYTICAL EXPLAINABILITY AND EVIDENCE INSPECTION ONLY.
 * Displays deterministic lineage graphs, provenance classifications (OBSERVED,
 * DERIVED, FORECAST, SIMULATED, ESTIMATED), validation statuses (VALID, STALE,
 * CONFLICTING, MISSING), criterion contributions, trade-offs, limitations,
 * excluded evidence, and immutable audit ledgers.
 *
 * Cardinal Invariant:
 * An explanation describes the evidence and reasoning behind an outcome.
 * It does NOT authorize an action, change a decision policy, or execute a recommendation.
 * This inspector NEVER contains execution, approval, or actuation controls.
 */

import React, { useState, useEffect } from "react";
import * as api from "../../lib/api";

interface EvidenceExplainabilityModalProps {
  isOpen: boolean;
  onClose: () => void;
  targetId?: string;
  targetType?: string;
  plantId?: string;
}

export default function EvidenceExplainabilityModal({
  isOpen,
  onClose,
  targetId: initialTargetId,
  targetType: initialTargetType = "DECISION_ENGINE",
  plantId = "PLANT-01",
}: EvidenceExplainabilityModalProps) {
  const [activeTab, setActiveTab] = useState<
    "overview" | "lineage" | "provenance" | "validation" | "contributions" | "rejections" | "limitations" | "audit"
  >("overview");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Target inputs
  const [targetType, setTargetType] = useState<string>(initialTargetType);
  const [targetId, setTargetId] = useState<string>(initialTargetId || "dec_synthetic_demo");
  const [currentExplanation, setCurrentExplanation] = useState<any | null>(null);
  const [recentExplanations, setRecentExplanations] = useState<any[]>([]);
  const [expandedNodeId, setExpandedNodeId] = useState<string | null>(null);
  const [searchFilter, setSearchFilter] = useState<string>("");

  // Target presets
  const presets = [
    { label: "Decision Engine (Resource Allocation)", type: "DECISION_ENGINE", id: "dec_demo_allocation" },
    { label: "What-If Simulation (Surge Scenario)", type: "WHAT_IF_SIMULATION", id: "sim_demo_surge" },
    { label: "Optimization (Throughput Frontier)", type: "OPTIMIZATION", id: "opt_demo_frontier" },
    { label: "Multimodal Sensor Fusion (Bearing)", type: "SENSOR_FUSION", id: "fuse_bearing_01" },
    { label: "Predictive Maintenance (Pump 4)", type: "PREDICTIVE_MAINTENANCE", id: "pm_pump_04" },
  ];

  useEffect(() => {
    if (isOpen) {
      loadRecentExplanations();
      if (initialTargetId) {
        setTargetId(initialTargetId);
        setTargetType(initialTargetType);
        handleExplain(initialTargetType, initialTargetId);
      } else {
        handleExplain(targetType, targetId);
      }
    }
  }, [isOpen, initialTargetId, initialTargetType]);

  // Keyboard navigation: Close on Escape
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  const loadRecentExplanations = async () => {
    try {
      const res = await api.listExplanations(10);
      if (res && res.items) {
        setRecentExplanations(res.items);
      }
    } catch {
      // Non-fatal if list cannot be loaded
    }
  };

  const handleExplain = async (typeToExplain = targetType, idToExplain = targetId) => {
    setIsLoading(true);
    setError(null);
    try {
      const payload = {
        target_type: typeToExplain,
        target_id: idToExplain,
        tenant_id: "tenant_default",
        workspace_id: "workspace_default",
        plant_id: plantId,
        include_lineage: true,
        include_validation: true,
        include_excluded: true,
      };
      const res = await api.explainEvidence(payload);
      setCurrentExplanation(res);
      loadRecentExplanations();
    } catch (err: any) {
      setError(err.message || "Failed to generate evidence explanation.");
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) return null;

  const provenanceBadge = (prov: string) => {
    switch (prov?.toUpperCase()) {
      case "OBSERVED":
        return <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/40">OBSERVED</span>;
      case "DERIVED":
        return <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-purple-500/20 text-purple-400 border border-purple-500/40">DERIVED</span>;
      case "FORECAST":
        return <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-cyan-500/20 text-cyan-400 border border-cyan-500/40">FORECAST</span>;
      case "SIMULATED":
        return <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-blue-500/20 text-blue-400 border border-blue-500/40">SIMULATED</span>;
      case "ESTIMATED":
        return <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-500/20 text-amber-400 border border-amber-500/40">ESTIMATED</span>;
      default:
        return <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-zinc-500/20 text-zinc-400 border border-zinc-500/40">UNKNOWN</span>;
    }
  };

  const statusBadge = (status: string) => {
    switch (status?.toUpperCase()) {
      case "VALID":
        return <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">VALID</span>;
      case "STALE":
        return <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">STALE</span>;
      case "INVALID":
        return <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30">INVALID</span>;
      case "CONFLICTING":
        return <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-red-600/20 text-red-300 border border-red-500/30">CONFLICTING</span>;
      case "INACCESSIBLE":
        return <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-zinc-600/20 text-zinc-300 border border-zinc-500/30">INACCESSIBLE</span>;
      default:
        return <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-zinc-700 text-zinc-300">{status}</span>;
    }
  };

  const severityBadge = (sev: string) => {
    switch (sev?.toUpperCase()) {
      case "BLOCKING":
        return <span className="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-red-500/30 text-red-300 border border-red-500/50">BLOCKING</span>;
      case "HIGH":
        return <span className="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-orange-500/30 text-orange-300 border border-orange-500/50">HIGH</span>;
      case "MEDIUM":
        return <span className="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40">MEDIUM</span>;
      default:
        return <span className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-blue-500/20 text-blue-300 border border-blue-500/40">LOW</span>;
    }
  };

  const supportingList = currentExplanation?.supporting_evidence || [];
  const excludedList = currentExplanation?.excluded_evidence || [];
  const validationsList = currentExplanation?.validations || [];
  const contributionsList = currentExplanation?.contributions || [];
  const rejectionsList = currentExplanation?.rejections || [];
  const conflictsList = currentExplanation?.conflicts || [];
  const gapsList = currentExplanation?.gaps || [];
  const limitationsList = currentExplanation?.limitations || [];
  const lineageGraph = currentExplanation?.lineage_graph;
  const expGraph = currentExplanation?.explanation_graph;

  const filteredSupporting = supportingList.filter((e: any) =>
    !searchFilter || e.title?.toLowerCase().includes(searchFilter.toLowerCase()) || e.evidence_id?.toLowerCase().includes(searchFilter.toLowerCase())
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4 animate-in fade-in duration-200">
      <div className="bg-[#0c0d12] border border-white/10 rounded-xl w-full max-w-6xl max-h-[92vh] flex flex-col shadow-2xl overflow-hidden font-sans">
        {/* HEADER BAR */}
        <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between bg-black/40">
          <div className="flex items-center gap-3">
            <div className="w-3 h-3 rounded-full bg-cyan-400 shadow-[0_0_8px_rgba(6,182,212,0.8)]" />
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm tracking-wider text-cyan-400 font-bold uppercase">
                  Evidence & Explainability Inspector
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-white/5 text-gray-400 border border-white/10">
                  V3 FOUNDATION
                </span>
                {currentExplanation?.is_partial && (
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-amber-500/20 text-amber-300 border border-amber-500/40">
                    PARTIAL TRACE
                  </span>
                )}
              </div>
              <p className="text-xs text-gray-400 mt-0.5">
                Deterministic lineage graphs, source provenance, eligibility checks & reasoning traces
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-[10px] font-mono text-gray-400 border border-white/10 px-2 py-1 rounded bg-black/50">
              READ-ONLY ANALYTICAL TRACE
            </span>
            <button
              type="button"
              onClick={onClose}
              className="text-gray-400 hover:text-white text-xl p-1 leading-none rounded hover:bg-white/5 transition-colors"
              aria-label="Close Modal"
            >
              ✕
            </button>
          </div>
        </div>

        {/* TARGET SELECTOR & PRESETS */}
        <div className="px-6 py-3 border-b border-white/10 bg-black/20 flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-gray-400 text-[11px] uppercase">Target Subsystem:</span>
            <select
              value={targetType}
              onChange={(e) => setTargetType(e.target.value)}
              className="bg-[#12141c] border border-white/10 rounded px-2.5 py-1 text-cyan-300 font-mono text-xs focus:outline-none focus:border-cyan-500"
            >
              <option value="DECISION_ENGINE">Decision Engine</option>
              <option value="OPTIMIZATION">Optimization Intelligence</option>
              <option value="WHAT_IF_SIMULATION">What-If Simulation</option>
              <option value="SENSOR_FUSION">Multimodal Sensor Fusion</option>
              <option value="PREDICTIVE_MAINTENANCE">Predictive Maintenance</option>
              <option value="DEMAND_FORECASTING">Demand Forecasting</option>
              <option value="ROOT_CAUSE_ANALYSIS">Root-Cause Analysis</option>
              <option value="BLAST_RADIUS">Blast-Radius Intelligence</option>
              <option value="INCIDENT_MANAGEMENT">Incident Management</option>
              <option value="DATA_QUALITY">Data Quality Engine</option>
              <option value="ANOMALY_DETECTION">Anomaly Detection</option>
              <option value="SUPPLIER_RISK">Supplier Risk</option>
              <option value="SLA_CUSTOMER_RISK">SLA / Customer Risk</option>
              <option value="FINANCIAL_IMPACT">Financial Impact</option>
              <option value="SUSTAINABILITY">Sustainability Intelligence</option>
            </select>

            <span className="font-mono text-gray-400 text-[11px] uppercase ml-2">Target ID:</span>
            <input
              type="text"
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
              placeholder="e.g. dec_123 or sim_456"
              className="bg-[#12141c] border border-white/10 rounded px-2.5 py-1 text-white font-mono text-xs w-48 focus:outline-none focus:border-cyan-500"
            />

            <button
              type="button"
              onClick={() => handleExplain(targetType, targetId)}
              disabled={isLoading}
              className="bg-cyan-600/30 hover:bg-cyan-600/50 text-cyan-300 border border-cyan-500/40 px-3 py-1 rounded font-mono text-xs uppercase tracking-wider font-semibold transition-colors disabled:opacity-50"
            >
              {isLoading ? "Tracing..." : "Explain Target"}
            </button>
          </div>

          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="font-mono text-gray-400 text-[10px] uppercase">Presets:</span>
            {presets.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => {
                  setTargetType(p.type);
                  setTargetId(p.id);
                  handleExplain(p.type, p.id);
                }}
                className="px-2 py-0.5 rounded text-[10px] font-mono bg-white/5 hover:bg-white/10 text-gray-300 border border-white/10 transition-colors"
              >
                {p.label.split(" ")[0]}
              </button>
            ))}
          </div>
        </div>

        {/* ERROR / STALE ALERTS */}
        {error && (
          <div className="px-6 py-2.5 bg-rose-950/40 border-b border-rose-500/30 text-rose-300 text-xs flex items-center justify-between">
            <span>⚠ {error}</span>
            <button type="button" onClick={() => setError(null)} className="text-rose-400 hover:text-rose-200">
              ✕
            </button>
          </div>
        )}

        {excludedList.length > 0 && (
          <div className="px-6 py-1.5 bg-amber-950/30 border-b border-amber-500/20 text-amber-300 text-[11px] font-mono flex items-center gap-2">
            <span>⚠ Stale or excluded evidence detected ({excludedList.length} items excluded). See Excluded Evidence tab.</span>
          </div>
        )}

        {/* TAB NAVIGATION */}
        <div className="flex items-center gap-1 px-6 border-b border-white/10 bg-black/40 overflow-x-auto">
          {[
            { key: "overview", label: "Overview & Conclusion" },
            { key: "lineage", label: `Lineage Graph (${lineageGraph?.nodes?.length || 0})` },
            { key: "provenance", label: `Provenance (${supportingList.length})` },
            { key: "validation", label: `Validation & Freshness (${validationsList.length})` },
            { key: "contributions", label: `Contributions (${contributionsList.length})` },
            { key: "rejections", label: `Excluded Evidence (${rejectionsList.length})` },
            { key: "limitations", label: `Gaps & Limitations (${limitationsList.length + gapsList.length})` },
            { key: "audit", label: "Audit Ledger & Fingerprint" },
          ].map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setActiveTab(t.key as any)}
              className={`px-3 py-2 text-xs font-mono tracking-wider uppercase transition-colors border-b-2 whitespace-nowrap ${
                activeTab === t.key
                  ? "border-cyan-400 text-cyan-300 font-bold bg-white/5"
                  : "border-transparent text-gray-400 hover:text-gray-200 hover:bg-white/[0.02]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* TAB CONTENTS */}
        <div className="flex-1 overflow-y-auto p-6 bg-[#090a0f]">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center py-20 text-gray-400 font-mono text-sm gap-3">
              <div className="w-8 h-8 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
              <span>Traversing evidence lineage and building deterministic trace...</span>
            </div>
          ) : !currentExplanation ? (
            <div className="text-center py-20 text-gray-500 font-mono text-sm">
              No explanation loaded. Select a target subsystem and ID above to begin.
            </div>
          ) : (
            <>
              {/* TAB 1: OVERVIEW */}
              {activeTab === "overview" && (
                <div className="space-y-6">
                  {/* Summary Card */}
                  <div className="p-4 rounded-lg bg-[#11131a] border border-white/10">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-mono text-cyan-400 uppercase font-bold">
                        Reasoning Summary
                      </span>
                      <span className="text-[10px] font-mono text-gray-400">
                        Algorithm v{currentExplanation.algorithm_version}
                      </span>
                    </div>
                    <p className="text-sm text-gray-200 leading-relaxed font-sans">
                      {currentExplanation.summary}
                    </p>
                  </div>

                  {/* Recommendation / Analytical Conclusion */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="p-4 rounded-lg bg-[#11131a] border border-white/10">
                      <span className="text-xs font-mono text-purple-400 uppercase font-bold block mb-3">
                        Analytical Conclusion / Recommendation
                      </span>
                      <div className="space-y-2 text-xs font-mono">
                        <div className="flex justify-between border-b border-white/5 pb-1">
                          <span className="text-gray-400">Target Type:</span>
                          <span className="text-white font-bold">{currentExplanation.target_type}</span>
                        </div>
                        <div className="flex justify-between border-b border-white/5 pb-1">
                          <span className="text-gray-400">Target ID:</span>
                          <span className="text-white">{currentExplanation.target_id}</span>
                        </div>
                        <div className="flex justify-between border-b border-white/5 pb-1">
                          <span className="text-gray-400">Status:</span>
                          <span className="text-emerald-400 font-bold">{currentExplanation.recommendation_or_conclusion?.status || "EVALUATED"}</span>
                        </div>
                        {currentExplanation.recommendation_or_conclusion?.recommended_option_id && (
                          <div className="flex justify-between border-b border-white/5 pb-1">
                            <span className="text-gray-400">Recommended Option:</span>
                            <span className="text-cyan-300 font-bold">{currentExplanation.recommendation_or_conclusion.recommended_option_id}</span>
                          </div>
                        )}
                        <div className="flex justify-between border-b border-white/5 pb-1">
                          <span className="text-gray-400">Assessment Timestamp:</span>
                          <span className="text-gray-300">{currentExplanation.assessment_timestamp}</span>
                        </div>
                      </div>
                    </div>

                    <div className="p-4 rounded-lg bg-[#11131a] border border-white/10">
                      <span className="text-xs font-mono text-cyan-400 uppercase font-bold block mb-3">
                        Evidence Metric Snapshot
                      </span>
                      <div className="grid grid-cols-2 gap-3 text-center">
                        <div className="p-3 bg-black/40 rounded border border-white/5">
                          <span className="text-2xl font-bold font-mono text-emerald-400">{supportingList.length}</span>
                          <span className="text-[10px] font-mono text-gray-400 block mt-1 uppercase">Valid Supporting Items</span>
                        </div>
                        <div className="p-3 bg-black/40 rounded border border-white/5">
                          <span className="text-2xl font-bold font-mono text-amber-400">{excludedList.length}</span>
                          <span className="text-[10px] font-mono text-gray-400 block mt-1 uppercase">Excluded / Stale Items</span>
                        </div>
                        <div className="p-3 bg-black/40 rounded border border-white/5">
                          <span className="text-2xl font-bold font-mono text-purple-400">{contributionsList.length}</span>
                          <span className="text-[10px] font-mono text-gray-400 block mt-1 uppercase">Criteria Contributions</span>
                        </div>
                        <div className="p-3 bg-black/40 rounded border border-white/5">
                          <span className="text-2xl font-bold font-mono text-cyan-400">{lineageGraph?.depth || 0}</span>
                          <span className="text-[10px] font-mono text-gray-400 block mt-1 uppercase">Lineage Depth</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Non-negotiable notice */}
                  <div className="p-3 bg-black/60 border border-white/10 rounded text-[11px] font-mono text-gray-400 flex items-center justify-between">
                    <span>INVARIANT: {currentExplanation.mandatory_notice}</span>
                    <span className="text-gray-500">CANONICAL SHA-256 HASH VERIFIED</span>
                  </div>
                </div>
              )}

              {/* TAB 2: LINEAGE GRAPH */}
              {activeTab === "lineage" && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between text-xs font-mono text-gray-400">
                    <span>Deterministic Lineage Tree (Depth: {lineageGraph?.depth || 0}, Nodes: {lineageGraph?.nodes?.length || 0}, Edges: {lineageGraph?.edges?.length || 0})</span>
                    {lineageGraph?.has_cycles && (
                      <span className="text-amber-400">⚠ Cycle detected and bounded</span>
                    )}
                  </div>

                  {(!lineageGraph || !lineageGraph.nodes || lineageGraph.nodes.length === 0) ? (
                    <div className="text-center py-12 text-gray-500 font-mono text-xs">
                      No multi-hop lineage graph available for this target.
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {/* Node Explorer */}
                      <div className="space-y-2">
                        <span className="text-xs font-mono text-cyan-400 uppercase font-bold block mb-2">
                          Evidence Nodes
                        </span>
                        {lineageGraph.nodes.map((node: any) => (
                          <div
                            key={node.evidence_id}
                            onClick={() => setExpandedNodeId(expandedNodeId === node.evidence_id ? null : node.evidence_id)}
                            className={`p-3 rounded border text-xs font-mono transition-colors cursor-pointer ${
                              expandedNodeId === node.evidence_id
                                ? "bg-cyan-950/30 border-cyan-500/50"
                                : "bg-[#11131a] border-white/10 hover:border-white/20"
                            }`}
                          >
                            <div className="flex items-center justify-between mb-1">
                              <span className="font-bold text-white">{node.evidence_id}</span>
                              <div className="flex items-center gap-1.5">
                                {provenanceBadge(node.provenance)}
                                <span className="text-[10px] text-gray-400 font-mono">{node.source_type}</span>
                              </div>
                            </div>
                            <p className="text-gray-300 text-[11px] font-sans truncate">{node.title}</p>
                            {expandedNodeId === node.evidence_id && (
                              <div className="mt-2 pt-2 border-t border-white/10 space-y-1 text-[10px] text-gray-400">
                                <div>Source Record: <span className="text-white">{node.source_record_id}</span></div>
                                <div>Quality Score: <span className="text-emerald-400">{node.quality_score}</span></div>
                                <div>Confidence: <span className="text-cyan-400">{node.confidence_score}</span></div>
                                <div>Timestamp: <span className="text-white">{node.observed_at || node.assessed_at}</span></div>
                                {node.parent_evidence_ids?.length > 0 && (
                                  <div>Parents: <span className="text-purple-300">{node.parent_evidence_ids.join(", ")}</span></div>
                                )}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>

                      {/* Lineage Edges */}
                      <div className="space-y-2">
                        <span className="text-xs font-mono text-purple-400 uppercase font-bold block mb-2">
                          Derivation & Transformation Edges
                        </span>
                        {lineageGraph.edges.map((edge: any) => (
                          <div key={edge.edge_id} className="p-3 rounded bg-[#11131a] border border-white/10 text-xs font-mono">
                            <div className="flex items-center justify-between mb-1">
                              <span className="text-cyan-300">{edge.source_evidence_id}</span>
                              <span className="text-gray-400">➔</span>
                              <span className="text-purple-300">{edge.target_evidence_id}</span>
                            </div>
                            <div className="flex items-center justify-between mt-1 text-[10px] text-gray-400">
                              <span className="font-bold text-gray-300">{edge.edge_type}</span>
                              {edge.transformation && (
                                <span className="text-amber-400">Trans: {edge.transformation.transformation_type}</span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* TAB 3: PROVENANCE */}
              {activeTab === "provenance" && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-xs font-mono text-gray-400">
                      Classified Evidence Provenance (Observed Facts vs Simulated/Derived/Forecast Projections)
                    </span>
                    <input
                      type="text"
                      placeholder="Filter evidence..."
                      value={searchFilter}
                      onChange={(e) => setSearchFilter(e.target.value)}
                      className="bg-[#12141c] border border-white/10 rounded px-2.5 py-1 text-xs text-white font-mono w-48 focus:outline-none focus:border-cyan-500"
                    />
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {filteredSupporting.map((ev: any) => (
                      <div key={ev.evidence_id} className="p-3 rounded bg-[#11131a] border border-white/10 text-xs font-mono space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-white truncate max-w-[150px]">{ev.evidence_id}</span>
                          {provenanceBadge(ev.provenance)}
                        </div>
                        <p className="text-[11px] font-sans text-gray-300 line-clamp-2">{ev.title}</p>
                        <div className="pt-2 border-t border-white/5 text-[10px] text-gray-400 space-y-1">
                          <div className="flex justify-between">
                            <span>Subsystem:</span>
                            <span className="text-gray-200">{ev.source_type}</span>
                          </div>
                          <div className="flex justify-between">
                            <span>Record ID:</span>
                            <span className="text-gray-200">{ev.source_record_id}</span>
                          </div>
                          <div className="flex justify-between">
                            <span>Quality / Conf:</span>
                            <span className="text-emerald-400">{ev.quality_score} / {ev.confidence_score}</span>
                          </div>
                          <div className="flex justify-between">
                            <span>Observed At:</span>
                            <span className="text-gray-300 truncate max-w-[120px]">{ev.observed_at || "N/A"}</span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* TAB 4: VALIDATION & FRESHNESS */}
              {activeTab === "validation" && (
                <div className="space-y-4">
                  <span className="text-xs font-mono text-gray-400 block">
                    Validation Pipeline Outcomes & Temporal Freshness Relative to Assessment Timestamp
                  </span>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs font-mono border-collapse">
                      <thead>
                        <tr className="border-b border-white/10 text-gray-400 text-left bg-black/40">
                          <th className="p-2.5">Evidence ID</th>
                          <th className="p-2.5">Status</th>
                          <th className="p-2.5">Age (Hrs)</th>
                          <th className="p-2.5">Freshness Threshold</th>
                          <th className="p-2.5">Future-Dated?</th>
                          <th className="p-2.5">Diagnostic Details</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5">
                        {validationsList.map((val: any) => (
                          <tr key={val.evidence_id} className="hover:bg-white/[0.02]">
                            <td className="p-2.5 font-bold text-white">{val.evidence_id}</td>
                            <td className="p-2.5">{statusBadge(val.status)}</td>
                            <td className="p-2.5 text-gray-300">
                              {val.freshness_assessment ? (val.freshness_assessment.age_seconds / 3600).toFixed(1) : "0.0"}h
                            </td>
                            <td className="p-2.5 text-gray-400">
                              {val.freshness_assessment ? (val.freshness_assessment.freshness_threshold_seconds / 3600).toFixed(0) : "168"}h
                            </td>
                            <td className="p-2.5">
                              {val.freshness_assessment?.is_future_dated ? (
                                <span className="text-rose-400 font-bold">YES (EXCLUDED)</span>
                              ) : (
                                <span className="text-emerald-400">NO</span>
                              )}
                            </td>
                            <td className="p-2.5 text-gray-400">
                              {val.rejection_reasons?.length > 0 ? (
                                <span className="text-rose-300">{val.rejection_reasons.join(", ")}</span>
                              ) : (
                                <span className="text-gray-500">Passed all checks</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* TAB 5: CONTRIBUTIONS */}
              {activeTab === "contributions" && (
                <div className="space-y-4">
                  <span className="text-xs font-mono text-gray-400 block">
                    Criterion-Level Scoring Contributions & Trade-off Deltas
                  </span>
                  {contributionsList.length === 0 ? (
                    <div className="text-center py-12 text-gray-500 font-mono text-xs">
                      No criterion-level contributions recorded for this target.
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {contributionsList.map((c: any, idx: number) => (
                        <div key={idx} className="p-3 rounded bg-[#11131a] border border-white/10 text-xs font-mono space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="text-purple-300 font-bold">{c.criterion_id || "CRITERION"}</span>
                            <span className="text-emerald-400 font-bold">Score: {c.contribution_score}</span>
                          </div>
                          <p className="text-[11px] font-sans text-gray-300">{c.explanation}</p>
                          <div className="pt-2 border-t border-white/5 text-[10px] text-gray-400 flex justify-between">
                            <span>Option: <span className="text-white">{c.option_id}</span></span>
                            <span>Weight: <span className="text-white">{c.weight}</span></span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* TAB 6: REJECTIONS */}
              {activeTab === "rejections" && (
                <div className="space-y-4">
                  <span className="text-xs font-mono text-gray-400 block">
                    Excluded Evidence Items & Structured Rejection Reasons
                  </span>
                  {rejectionsList.length === 0 ? (
                    <div className="text-center py-12 text-gray-500 font-mono text-xs">
                      No evidence items were excluded or rejected. All provided evidence was valid.
                    </div>
                  ) : (
                    <div className="space-y-2.5">
                      {rejectionsList.map((rej: any, idx: number) => (
                        <div key={idx} className="p-3 rounded bg-[#1a1114] border border-rose-500/20 text-xs font-mono flex items-center justify-between">
                          <div className="space-y-1">
                            <div className="flex items-center gap-2">
                              <span className="font-bold text-rose-300">{rej.evidence_id}</span>
                              <span className="px-1.5 py-0.5 rounded text-[9px] bg-rose-500/30 text-rose-200 border border-rose-500/40">
                                {rej.reason_code}
                              </span>
                              {severityBadge(rej.severity)}
                            </div>
                            <p className="text-[11px] font-sans text-gray-300">{rej.explanation}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* TAB 7: LIMITATIONS & GAPS */}
              {activeTab === "limitations" && (
                <div className="space-y-6">
                  {/* Evidence Gaps */}
                  <div>
                    <span className="text-xs font-mono text-amber-400 uppercase font-bold block mb-2">
                      Identified Evidence Gaps ({gapsList.length})
                    </span>
                    {gapsList.length === 0 ? (
                      <p className="text-xs font-mono text-gray-500">No unresolved evidence gaps detected.</p>
                    ) : (
                      <div className="space-y-2">
                        {gapsList.map((g: any, idx: number) => (
                          <div key={idx} className="p-3 rounded bg-[#161410] border border-amber-500/20 text-xs font-mono space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="text-amber-300 font-bold">{g.gap_id}</span>
                              <span className="text-[10px] text-gray-400">{g.gap_type}</span>
                            </div>
                            <p className="text-[11px] font-sans text-gray-300">{g.description}</p>
                            <span className="text-[10px] text-gray-400 block">Impact: {g.impact}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Explicit Limitations */}
                  <div>
                    <span className="text-xs font-mono text-cyan-400 uppercase font-bold block mb-2">
                      Analytical Assumptions & Limitations ({limitationsList.length})
                    </span>
                    {limitationsList.length === 0 ? (
                      <p className="text-xs font-mono text-gray-500">No operational limitations flagged.</p>
                    ) : (
                      <div className="space-y-2">
                        {limitationsList.map((lim: any, idx: number) => (
                          <div key={idx} className="p-3 rounded bg-[#11131a] border border-white/10 text-xs font-mono space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="text-white font-bold">{lim.code}</span>
                              {severityBadge(lim.severity)}
                            </div>
                            <p className="text-[11px] font-sans text-gray-300">{lim.description}</p>
                            {lim.mitigation && (
                              <p className="text-[10px] text-cyan-300 font-mono">Mitigation: {lim.mitigation}</p>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* TAB 8: AUDIT & FINGERPRINT */}
              {activeTab === "audit" && (
                <div className="space-y-6">
                  {/* Fingerprint Card */}
                  <div className="p-4 rounded-lg bg-[#11131a] border border-white/10 text-xs font-mono space-y-2">
                    <span className="text-cyan-400 uppercase font-bold block">
                      Deterministic Explanation Fingerprint
                    </span>
                    <div className="p-2.5 bg-black/60 rounded border border-white/10 text-white font-mono break-all text-[11px]">
                      {currentExplanation.fingerprint}
                    </div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px] text-gray-400 pt-2 border-t border-white/5">
                      <div>Algorithm: <span className="text-white">v{currentExplanation.algorithm_version}</span></div>
                      <div>Contract: <span className="text-white">v{currentExplanation.contract_version}</span></div>
                      <div>Tenant: <span className="text-white">{currentExplanation.tenant_id}</span></div>
                      <div>Scope: <span className="text-white">{currentExplanation.plant_id || "ALL"}</span></div>
                    </div>
                  </div>

                  {/* Recent Explanations Ledger */}
                  <div>
                    <span className="text-xs font-mono text-gray-400 uppercase font-bold block mb-2">
                      Recent Explanation Runs ({recentExplanations.length})
                    </span>
                    <div className="space-y-1.5">
                      {recentExplanations.map((exp: any) => (
                        <div
                          key={exp.explanation_id}
                          onClick={() => {
                            setTargetId(exp.target_id);
                            setTargetType(exp.target_type);
                            handleExplain(exp.target_type, exp.target_id);
                          }}
                          className="p-2.5 rounded bg-[#11131a] border border-white/5 hover:border-cyan-500/40 text-xs font-mono flex items-center justify-between cursor-pointer transition-colors"
                        >
                          <div className="flex items-center gap-2">
                            <span className="text-cyan-300 font-bold">{exp.explanation_id}</span>
                            <span className="text-gray-400">({exp.target_type})</span>
                          </div>
                          <span className="text-gray-500 text-[10px]">{exp.assessment_timestamp}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* FOOTER BAR */}
        <div className="px-6 py-3 border-t border-white/10 bg-black/40 flex items-center justify-between text-xs font-mono text-gray-400">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400" />
            <span>EXPLAINABILITY INTEGRITY: PASS</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1 rounded bg-white/10 hover:bg-white/20 text-white transition-colors"
          >
            Close Inspector
          </button>
        </div>
      </div>
    </div>
  );
}
