"use client";

/**
 * frontend/app/components/DecisionEngineModal.tsx
 *
 * SageCommand V3 — Decision Engine Foundation Modal (Prompt 30)
 *
 * ANALYTICAL DECISION SUPPORT ONLY.
 * Displays governed decision recommendations, candidate alternatives,
 * criteria scoring, constraint & policy evaluations, trade-off comparisons,
 * upstream evidence references, and immutable audit ledgers.
 *
 * Cardinal Invariant:
 * DECISION ENGINE -> RECOMMENDATION -> HUMAN / AUTHORIZED OPERATOR.
 * This component NEVER executes operational commands, writes to PLCs/controllers,
 * dispatches work orders, issues purchase orders, or mutates physical systems.
 */

import React, { useState, useEffect } from "react";
import * as api from "../../lib/api";

interface DecisionEngineModalProps {
  isOpen: boolean;
  onClose: () => void;
  plantId?: string;
}

export default function DecisionEngineModal({
  isOpen,
  onClose,
  plantId = "PLANT-01",
}: DecisionEngineModalProps) {
  const [activeTab, setActiveTab] = useState<
    "recommendation" | "alternatives" | "criteria" | "constraints" | "tradeoffs" | "evidence" | "audit"
  >("recommendation");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form / Scenario state
  const [scenarioKey, setScenarioKey] = useState<"capacity" | "demand" | "maintenance">("capacity");
  const [currentEvaluation, setCurrentEvaluation] = useState<any | null>(null);

  // Pre-configured analytical scenarios
  const scenarios = {
    capacity: {
      title: "Critical Line Capacity & Shift Reallocation",
      type: "RESOURCE_ALLOCATION",
      description: "Balance production throughput against thermal stress and carbon emissions for high-demand window.",
      options: [
        {
          option_id: "OPT_DUAL_SHIFT",
          name: "Dual-Shift High Rate (Line A + B)",
          category: "OPERATIONAL_SHIFT",
          parameters: { max_capacity_pct: 95.0, shift_count: 2, operator_crew: 8 },
          expected_outcomes: { throughput_units: 1250.0, cost_usd: 8400.0, energy_kwh: 3200.0, risk_index: 0.22, thermal_stress_c: 68.5 },
          tags: ["HIGH_THROUGHPUT", "SURGE"],
        },
        {
          option_id: "OPT_AUTOMATED_CELL",
          name: "Automated Flexible Cell Allocation",
          category: "AUTOMATION",
          parameters: { max_capacity_pct: 82.0, shift_count: 3, operator_crew: 3 },
          expected_outcomes: { throughput_units: 1100.0, cost_usd: 6200.0, energy_kwh: 2450.0, risk_index: 0.15, thermal_stress_c: 54.0 },
          tags: ["BALANCED", "LOW_RISK", "ENERGY_EFFICIENT"],
        },
        {
          option_id: "OPT_STANDARD_SINGLE",
          name: "Standard Baseline Single Shift",
          category: "BASELINE",
          parameters: { max_capacity_pct: 65.0, shift_count: 1, operator_crew: 6 },
          expected_outcomes: { throughput_units: 750.0, cost_usd: 4800.0, energy_kwh: 1800.0, risk_index: 0.08, thermal_stress_c: 42.0 },
          tags: ["CONSERVATIVE", "MINIMUM_COST"],
        },
      ],
      criteria: [
        { criterion_id: "throughput_units", name: "Throughput (Units/Day)", criterion_type: "THROUGHPUT", direction: "MAXIMIZE", weight: 3.5, unit: "units" },
        { criterion_id: "cost_usd", name: "Operating Cost", criterion_type: "COST", direction: "MINIMIZE", weight: 2.5, unit: "USD" },
        { criterion_id: "energy_kwh", name: "Energy Consumption", criterion_type: "ENERGY", direction: "MINIMIZE", weight: 2.0, unit: "kWh" },
        { criterion_id: "risk_index", name: "Operational Risk Index", criterion_type: "RISK", direction: "MINIMIZE", weight: 2.0, unit: "score" },
      ],
      constraints: [
        { constraint_id: "C_MAX_THERMAL", name: "Thermal Ceiling Limit", constraint_type: "SAFETY", operator: "<=", threshold_value: 70.0, hard_or_soft: "HARD", target_field: "thermal_stress_c", unit: "°C" },
        { constraint_id: "C_MIN_THROUGHPUT", name: "Minimum SLA Target", constraint_type: "DEMAND", operator: ">=", threshold_value: 800.0, hard_or_soft: "HARD", target_field: "throughput_units", unit: "units" },
      ],
      policies: [
        { policy_id: "POL_SAFETY_GOVERNANCE", name: "Plant Thermal Safety Ceiling", version: "2.1", rules: { thermal_stress_c: 75.0 }, is_active: true },
      ],
    },
    demand: {
      title: "Surge Fulfillment & Supplier Routing",
      type: "DEMAND_FULFILLMENT",
      description: "Route surge components across certified tier-1 suppliers considering lead time and tariff risk.",
      options: [
        {
          option_id: "OPT_LOCAL_FAST",
          name: "Regional Preferred Supplier (Air Express)",
          category: "LOGISTICS_AIR",
          parameters: { supplier_tier: 1, delivery_days: 2 },
          expected_outcomes: { cost_usd: 14500.0, lead_time_days: 2.0, supplier_reliability: 0.98, carbon_kg: 850.0 },
          tags: ["FAST", "HIGH_COST"],
        },
        {
          option_id: "OPT_HYBRID_SPLIT",
          name: "Dual-Source Split Fulfillment",
          category: "HYBRID",
          parameters: { supplier_tier: 1, delivery_days: 5 },
          expected_outcomes: { cost_usd: 9800.0, lead_time_days: 4.5, supplier_reliability: 0.94, carbon_kg: 420.0 },
          tags: ["BALANCED", "RECOMMENDED_SPLIT"],
        },
      ],
      criteria: [
        { criterion_id: "cost_usd", name: "Total Cost", criterion_type: "COST", direction: "MINIMIZE", weight: 3.0, unit: "USD" },
        { criterion_id: "lead_time_days", name: "Lead Time", criterion_type: "TIME", direction: "MINIMIZE", weight: 4.0, unit: "days" },
        { criterion_id: "supplier_reliability", name: "Reliability", criterion_type: "RELIABILITY", direction: "MAXIMIZE", weight: 3.0, unit: "%" },
      ],
      constraints: [
        { constraint_id: "C_MAX_LEAD_TIME", name: "Max Lead Time Window", constraint_type: "TIME", operator: "<=", threshold_value: 7.0, hard_or_soft: "HARD", target_field: "lead_time_days", unit: "days" },
      ],
      policies: [
        { policy_id: "POL_SUPPLIER_ESG", name: "Supplier ESG Compliance", version: "1.4", rules: { supplier_tier: [1, 2] }, is_active: true },
      ],
    },
    maintenance: {
      title: "Predictive Asset Overhaul Window",
      type: "MAINTENANCE_PRIORITIZATION",
      description: "Evaluate overhaul timing for coolant pump bearing vs production run schedule.",
      options: [
        {
          option_id: "OPT_IMMEDIATE_STOP",
          name: "Immediate Production Hold & Overhaul",
          category: "PREVENTIVE",
          parameters: { window_hours: 4 },
          expected_outcomes: { downtime_hours: 4.0, cost_usd: 3500.0, failure_probability: 0.01, safety_margin: 0.95 },
          tags: ["SAFETY_FIRST", "IMMEDIATE"],
        },
        {
          option_id: "OPT_PLANNED_SHIFT_CHANGE",
          name: "Defer to Next Scheduled Shift Change",
          category: "SCHEDULED",
          parameters: { window_hours: 12 },
          expected_outcomes: { downtime_hours: 1.5, cost_usd: 1800.0, failure_probability: 0.07, safety_margin: 0.88 },
          tags: ["MINIMAL_DOWNTIME"],
        },
      ],
      criteria: [
        { criterion_id: "failure_probability", name: "Failure Probability", criterion_type: "RISK", direction: "MINIMIZE", weight: 5.0, unit: "prob" },
        { criterion_id: "downtime_hours", name: "Production Downtime", criterion_type: "TIME", direction: "MINIMIZE", weight: 3.0, unit: "hrs" },
        { criterion_id: "cost_usd", name: "Overhaul Cost", criterion_type: "COST", direction: "MINIMIZE", weight: 2.0, unit: "USD" },
      ],
      constraints: [
        { constraint_id: "C_MAX_FAILURE_PROB", name: "Failure Ceiling", constraint_type: "SAFETY", operator: "<=", threshold_value: 0.10, hard_or_soft: "HARD", target_field: "failure_probability", unit: "prob" },
      ],
      policies: [
        { policy_id: "POL_SAFETY_HOLD", name: "ISO-13849 Safety Critical Hold", version: "3.0", rules: { safety_margin: 0.80 }, is_active: true },
      ],
    },
  };

  useEffect(() => {
    if (isOpen && !currentEvaluation) {
      handleRunEvaluation();
    }
  }, [isOpen, scenarioKey]);

  const handleRunEvaluation = async () => {
    setIsLoading(true);
    setError(null);

    const s = scenarios[scenarioKey];
    const payload = {
      tenant_id: "tenant_default",
      workspace_id: "workspace_default",
      plant_id: plantId,
      decision_type: s.type,
      title: s.title,
      description: s.description,
      scope: "PLANT",
      horizon: "SHORT_TERM",
      options: s.options,
      criteria: s.criteria,
      constraints: s.constraints,
      policies: s.policies,
      evidence_references: [
        {
          evidence_id: `EV_SIM_${scenarioKey.toUpperCase()}`,
          source_subsystem: "WHAT_IF_SIMULATION",
          source_record_id: "sim_scenario_v3_alpha",
          tenant_id: "tenant_default",
          workspace_id: "workspace_default",
          plant_id: plantId,
          timestamp: new Date().toISOString(),
          provenance: "SIMULATED",
          quality_score: 0.96,
          confidence: 0.92,
          is_valid: true,
          details: { scenario_seed: 42, model_version: "3.0" },
        },
        {
          evidence_id: `EV_OPT_${scenarioKey.toUpperCase()}`,
          source_subsystem: "OPTIMIZATION",
          source_record_id: "opt_frontier_v3_beta",
          tenant_id: "tenant_default",
          workspace_id: "workspace_default",
          plant_id: plantId,
          timestamp: new Date().toISOString(),
          provenance: "DERIVED",
          quality_score: 0.98,
          confidence: 0.95,
          is_valid: true,
          details: { pareto_efficiency: 0.94 },
        },
      ],
      comparison_method: "WEIGHTED_SCORING",
    };

    try {
      const res = await api.evaluateDecision(payload);
      setCurrentEvaluation(res);
    } catch (err: any) {
      setError(err?.message || "Failed to evaluate decision problem.");
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) return null;

  const rec = currentEvaluation?.recommendation;
  const alternatives = rec?.alternatives || [];
  const limitations = currentEvaluation?.limitations || [];
  const tradeoffs = rec?.tradeoffs || [];
  const evidenceSnapshot = currentEvaluation?.evidence_snapshot || [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="relative w-full max-w-6xl max-h-[92vh] flex flex-col rounded-xl border border-violet-500/40 bg-zinc-950 text-zinc-100 shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-zinc-800 px-6 py-4 bg-zinc-900/60">
          <div className="flex items-center space-x-3">
            <div className="h-3 w-3 rounded-full bg-violet-400 animate-pulse" />
            <h2 className="text-lg font-semibold tracking-wide text-zinc-100 flex items-center gap-2">
              Decision Engine Foundation
              <span className="text-xs font-mono font-normal px-2 py-0.5 rounded bg-violet-950/80 border border-violet-600/40 text-violet-300">
                PROMPT 30 • GOVERNED RECOMMENDATION
              </span>
            </h2>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100 transition-colors"
            aria-label="Close Modal"
          >
            ✕
          </button>
        </div>

        {/* Mandatory Architectural Boundary Notice */}
        <div className="bg-amber-950/50 border-b border-amber-500/40 px-6 py-2.5 flex items-center justify-between text-xs text-amber-200">
          <div className="flex items-center gap-2 font-mono">
            <span className="font-bold text-amber-400">⚠️ MANDATORY NOTICE:</span>
            <span>DECISION RECOMMENDATION — NOT AUTHORIZED AND NOT EXECUTED</span>
          </div>
          <span className="text-zinc-400 font-mono text-[11px] hidden sm:inline">
            ANALYTICAL DECISION SUPPORT ONLY
          </span>
        </div>

        {/* Control Toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-4 px-6 py-3 border-b border-zinc-800/80 bg-zinc-900/30 text-xs">
          <div className="flex items-center gap-2">
            <span className="text-zinc-400">Analytical Problem Scenario:</span>
            <select
              value={scenarioKey}
              onChange={(e) => {
                setScenarioKey(e.target.value as any);
                setCurrentEvaluation(null);
              }}
              className="bg-zinc-800 border border-zinc-700 rounded px-2.5 py-1 text-zinc-200 font-medium focus:border-violet-500 focus:outline-none"
            >
              <option value="capacity">Capacity & Shift Reallocation</option>
              <option value="demand">Surge Demand & Supplier Routing</option>
              <option value="maintenance">Predictive Asset Overhaul Window</option>
            </select>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleRunEvaluation}
              disabled={isLoading}
              className="px-3 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-500 text-white font-medium flex items-center gap-1.5 transition-colors disabled:opacity-50"
            >
              {isLoading ? "Evaluating Pipeline..." : "Re-evaluate Problem"}
            </button>
          </div>
        </div>

        {/* Navigation Tabs */}
        <div className="flex border-b border-zinc-800 px-6 bg-zinc-900/40 text-xs font-medium space-x-1 overflow-x-auto">
          {[
            { id: "recommendation", label: "Recommendation" },
            { id: "alternatives", label: `Alternatives (${alternatives.length})` },
            { id: "criteria", label: "Criteria & Weights" },
            { id: "constraints", label: "Constraints & Policies" },
            { id: "tradeoffs", label: `Trade-offs (${tradeoffs.length})` },
            { id: "evidence", label: `Evidence (${evidenceSnapshot.length})` },
            { id: "audit", label: "Audit Ledger" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`px-3.5 py-2.5 border-b-2 transition-colors whitespace-nowrap ${
                activeTab === tab.id
                  ? "border-violet-400 text-violet-300 font-semibold"
                  : "border-transparent text-zinc-400 hover:text-zinc-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {error && (
            <div className="p-3.5 rounded-lg bg-red-950/50 border border-red-500/40 text-red-200 text-xs font-mono">
              Error: {error}
            </div>
          )}

          {/* TAB 1: RECOMMENDATION */}
          {activeTab === "recommendation" && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="p-4 rounded-xl border border-zinc-800 bg-zinc-900/50">
                  <span className="text-zinc-400 text-xs uppercase tracking-wider">Recommended Alternative</span>
                  <div className="text-lg font-bold text-violet-300 mt-1">
                    {rec?.recommended_option_id || "None Feasible"}
                  </div>
                  <span className="text-xs text-zinc-400 mt-0.5 block">
                    Status: <span className="text-emerald-400 font-mono font-medium">{rec?.recommendation_status}</span>
                  </span>
                </div>

                <div className="p-4 rounded-xl border border-zinc-800 bg-zinc-900/50">
                  <span className="text-zinc-400 text-xs uppercase tracking-wider">Confidence Index</span>
                  <div className="text-lg font-bold text-emerald-400 mt-1">
                    {rec?.confidence ? `${(rec.confidence * 100).toFixed(1)}%` : "N/A"}
                  </div>
                  <span className="text-xs text-zinc-400 mt-0.5 block">
                    Uncertainty: {rec?.uncertainty_summary || "Deterministic"}
                  </span>
                </div>

                <div className="p-4 rounded-xl border border-zinc-800 bg-zinc-900/50">
                  <span className="text-zinc-400 text-xs uppercase tracking-wider">Fingerprint (SHA-256)</span>
                  <div className="text-xs font-mono text-cyan-300 truncate mt-1">
                    {currentEvaluation?.fingerprint || "N/A"}
                  </div>
                  <span className="text-[11px] text-zinc-500 mt-1 block">
                    Timestamp: {currentEvaluation?.assessment_timestamp?.slice(0, 19)}Z
                  </span>
                </div>
              </div>

              {/* Rationale Card */}
              <div className="p-4 rounded-xl border border-violet-500/30 bg-violet-950/20 space-y-2">
                <h3 className="text-xs font-mono uppercase text-violet-300 tracking-wider">Primary Rationale</h3>
                <p className="text-sm text-zinc-200 leading-relaxed font-sans">
                  {rec?.primary_rationale || "Running deterministic evaluation..."}
                </p>
              </div>

              {/* Top Alternative Card */}
              {alternatives.length > 0 && (
                <div className="p-4 rounded-xl border border-zinc-800 bg-zinc-900/40 space-y-3">
                  <h3 className="text-xs font-mono uppercase text-zinc-400 tracking-wider">
                    Highest Ranking Course of Action
                  </h3>
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-3 rounded-lg bg-zinc-800/50 border border-zinc-700/60">
                    <div>
                      <div className="text-sm font-semibold text-zinc-100 flex items-center gap-2">
                        {alternatives[0].option_name}
                        <span className="text-xs font-mono px-2 py-0.5 rounded bg-emerald-950 border border-emerald-500/50 text-emerald-300">
                          RANK #1
                        </span>
                      </div>
                      <div className="text-xs text-zinc-400 mt-1 font-mono">
                        ID: {alternatives[0].option_id} • Score: {alternatives[0].composite_score.toFixed(4)}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs px-2 py-1 rounded bg-zinc-700/60 text-zinc-200">
                        Feasible: {alternatives[0].is_feasible ? "✓ Yes" : "✗ No"}
                      </span>
                      <span className="text-xs px-2 py-1 rounded bg-zinc-700/60 text-zinc-200">
                        Policy Compliant: {alternatives[0].is_policy_compliant ? "✓ Yes" : "✗ No"}
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TAB 2: ALTERNATIVES & RANKING */}
          {activeTab === "alternatives" && (
            <div className="space-y-3">
              <div className="overflow-x-auto rounded-xl border border-zinc-800">
                <table className="w-full text-left text-xs text-zinc-300">
                  <thead className="bg-zinc-900 text-zinc-400 border-b border-zinc-800 uppercase font-mono text-[11px]">
                    <tr>
                      <th className="px-4 py-3">Rank</th>
                      <th className="px-4 py-3">Option</th>
                      <th className="px-4 py-3">Composite Score</th>
                      <th className="px-4 py-3">Feasibility</th>
                      <th className="px-4 py-3">Policy Status</th>
                      <th className="px-4 py-3">Recommendation</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800 bg-zinc-950">
                    {alternatives.map((alt: any) => (
                      <tr key={alt.option_id} className="hover:bg-zinc-900/50 transition-colors">
                        <td className="px-4 py-3 font-mono font-bold text-violet-400">#{alt.rank}</td>
                        <td className="px-4 py-3 font-medium text-zinc-100">
                          {alt.option_name}
                          <div className="text-[11px] font-mono text-zinc-400">{alt.option_id}</div>
                        </td>
                        <td className="px-4 py-3 font-mono text-emerald-400">
                          {alt.composite_score.toFixed(4)}
                        </td>
                        <td className="px-4 py-3">
                          {alt.is_feasible ? (
                            <span className="text-emerald-400 font-mono">FEASIBLE</span>
                          ) : (
                            <span className="text-red-400 font-mono">INFEASIBLE</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          {alt.is_policy_compliant ? (
                            <span className="text-emerald-400 font-mono">COMPLIANT</span>
                          ) : (
                            <span className="text-amber-400 font-mono">BLOCKED</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          {alt.is_recommended ? (
                            <span className="px-2 py-0.5 rounded bg-violet-900/60 text-violet-200 border border-violet-500/40 text-[11px] font-mono font-medium">
                              RECOMMENDED
                            </span>
                          ) : (
                            <span className="text-zinc-500 text-[11px]">Alternative</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB 3: CRITERIA & WEIGHTS */}
          {activeTab === "criteria" && (
            <div className="space-y-3">
              <div className="overflow-x-auto rounded-xl border border-zinc-800">
                <table className="w-full text-left text-xs text-zinc-300">
                  <thead className="bg-zinc-900 text-zinc-400 border-b border-zinc-800 uppercase font-mono text-[11px]">
                    <tr>
                      <th className="px-4 py-3">Criterion</th>
                      <th className="px-4 py-3">Category</th>
                      <th className="px-4 py-3">Direction</th>
                      <th className="px-4 py-3">Weight</th>
                      <th className="px-4 py-3">Unit</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800 bg-zinc-950">
                    {(currentEvaluation?.criterion_evaluations || []).map((c: any, i: number) => (
                      <tr key={i} className="hover:bg-zinc-900/50">
                        <td className="px-4 py-3 font-medium text-zinc-100">{c.criterion_id}</td>
                        <td className="px-4 py-3 font-mono text-zinc-400">ANALYTICAL</td>
                        <td className="px-4 py-3 font-mono text-cyan-300">{c.direction}</td>
                        <td className="px-4 py-3 font-mono text-emerald-300">{c.weighted_score.toFixed(4)}</td>
                        <td className="px-4 py-3 font-mono text-zinc-400">{c.unit || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB 4: CONSTRAINTS & POLICIES */}
          {activeTab === "constraints" && (
            <div className="space-y-4">
              <div className="space-y-2">
                <h4 className="text-xs font-mono uppercase text-zinc-400">Hard & Soft Operational Constraints</h4>
                <div className="divide-y divide-zinc-800 rounded-xl border border-zinc-800 bg-zinc-950 overflow-hidden">
                  {(currentEvaluation?.constraint_evaluations || []).map((con: any, i: number) => (
                    <div key={i} className="p-3 text-xs flex items-center justify-between">
                      <div>
                        <div className="font-semibold text-zinc-200">{con.constraint_id}</div>
                        <div className="text-[11px] text-zinc-400">{con.explanation}</div>
                      </div>
                      <span className={`px-2 py-0.5 rounded text-[11px] font-mono ${con.satisfied ? "bg-emerald-950 text-emerald-300" : "bg-red-950 text-red-300"}`}>
                        {con.satisfied ? "SATISFIED" : "VIOLATED"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <h4 className="text-xs font-mono uppercase text-zinc-400">Governance Policies Evaluated</h4>
                <div className="divide-y divide-zinc-800 rounded-xl border border-zinc-800 bg-zinc-950 overflow-hidden">
                  {(currentEvaluation?.policy_evaluations || []).map((pol: any, i: number) => (
                    <div key={i} className="p-3 text-xs flex items-center justify-between">
                      <div>
                        <div className="font-semibold text-zinc-200">{pol.policy_id} v{pol.policy_version}</div>
                        <div className="text-[11px] text-zinc-400">{pol.reason}</div>
                      </div>
                      <span className="px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 text-[11px] font-mono">
                        {pol.status}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* TAB 5: TRADEOFFS & SENSITIVITY */}
          {activeTab === "tradeoffs" && (
            <div className="space-y-3">
              {tradeoffs.length === 0 ? (
                <div className="p-6 text-center text-xs text-zinc-500 font-mono">
                  No material trade-offs or single alternative evaluated.
                </div>
              ) : (
                tradeoffs.map((t: any, i: number) => (
                  <div key={i} className="p-3.5 rounded-xl border border-zinc-800 bg-zinc-900/40 text-xs space-y-1">
                    <div className="flex items-center justify-between font-mono">
                      <span className="font-semibold text-violet-300">{t.criterion_a}</span>
                      <span className="text-cyan-400">Score Delta: {t.impact_delta > 0 ? `+${t.impact_delta}` : t.impact_delta}</span>
                    </div>
                    <p className="text-zinc-300">{t.description}</p>
                  </div>
                ))
              )}
            </div>
          )}

          {/* TAB 6: EVIDENCE & PROVENANCE */}
          {activeTab === "evidence" && (
            <div className="space-y-3">
              <div className="overflow-x-auto rounded-xl border border-zinc-800">
                <table className="w-full text-left text-xs text-zinc-300">
                  <thead className="bg-zinc-900 text-zinc-400 border-b border-zinc-800 uppercase font-mono text-[11px]">
                    <tr>
                      <th className="px-4 py-3">Source Subsystem</th>
                      <th className="px-4 py-3">Record ID</th>
                      <th className="px-4 py-3">Provenance</th>
                      <th className="px-4 py-3">Quality</th>
                      <th className="px-4 py-3">Confidence</th>
                      <th className="px-4 py-3">Validity</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800 bg-zinc-950">
                    {evidenceSnapshot.map((ev: any, i: number) => (
                      <tr key={i} className="hover:bg-zinc-900/50">
                        <td className="px-4 py-3 font-semibold text-violet-300">{ev.source_subsystem}</td>
                        <td className="px-4 py-3 font-mono text-zinc-400">{ev.source_record_id}</td>
                        <td className="px-4 py-3 font-mono text-cyan-300">{ev.provenance}</td>
                        <td className="px-4 py-3 font-mono text-emerald-400">{(ev.quality_score * 100).toFixed(0)}%</td>
                        <td className="px-4 py-3 font-mono text-emerald-400">{(ev.confidence * 100).toFixed(0)}%</td>
                        <td className="px-4 py-3 font-mono text-emerald-400">{ev.is_valid ? "VALID" : "STALE"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB 7: AUDIT LEDGER */}
          {activeTab === "audit" && (
            <div className="space-y-3">
              <div className="p-4 rounded-xl border border-zinc-800 bg-zinc-900/30 text-xs font-mono space-y-2">
                <div className="text-zinc-400">Audit Ledger Verification Record:</div>
                <div className="text-zinc-200">
                  Decision ID: <span className="text-violet-300">{currentEvaluation?.decision_id}</span>
                </div>
                <div className="text-zinc-200 truncate">
                  SHA-256 Fingerprint: <span className="text-cyan-300">{currentEvaluation?.fingerprint}</span>
                </div>
                <div className="text-zinc-200">
                  Assessment Timestamp: <span className="text-emerald-300">{currentEvaluation?.assessment_timestamp}</span>
                </div>
                <div className="text-zinc-200">
                  Status: <span className="text-amber-300">{currentEvaluation?.status}</span>
                </div>
                <div className="text-zinc-400 text-[11px] pt-2 border-t border-zinc-800">
                  All evaluation records are appended to SQLite WAL audit ledger with cryptographic checksums.
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="flex items-center justify-between border-t border-zinc-800 px-6 py-3 bg-zinc-900/60 text-xs text-zinc-400">
          <span className="font-mono text-[11px]">
            Tenant: tenant_default • Plant: {plantId} • Scope: PLANT
          </span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 font-medium transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
