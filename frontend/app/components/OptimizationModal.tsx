"use client";

/**
 * frontend/app/components/OptimizationModal.tsx
 *
 * SageCommand V3 — Optimization Intelligence Modal (Prompt 29)
 *
 * ANALYTICAL DECISION SUPPORT ONLY.
 * Displays governed analytical recommendations, candidate evaluations,
 * multi-objective trade-offs, constraint evaluations, sensitivity perturbations,
 * and auditable evidence chains.
 *
 * Cardinal Invariant:
 * OPTIMIZATION -> RECOMMENDATION -> HUMAN / AUTHORIZED DECISION.
 * This component NEVER executes operational commands, writes to PLCs/controllers,
 * dispatches work orders, issues purchase orders, or mutates physical systems.
 */

import React, { useState, useEffect } from "react";
import * as api from "../../lib/api";

interface OptimizationModalProps {
  isOpen: boolean;
  onClose: () => void;
  plantId?: string;
}

export default function OptimizationModal({
  isOpen,
  onClose,
  plantId = "PLANT-01",
}: OptimizationModalProps) {
  const [activeTab, setActiveTab] = useState<
    "problem" | "objectives" | "constraints" | "results" | "tradeoffs" | "sensitivity" | "evidence"
  >("results");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [problemName, setProblemName] = useState("Critical Line Capacity & Risk Allocation");
  const [decisionScope, setDecisionScope] = useState("PLANT");
  const [solverMethod, setSolverMethod] = useState("EXHAUSTIVE_BOUNDED");
  const [multiObjMethod, setMultiObjMethod] = useState("WEIGHTED_SUM");

  // Current Optimization Result
  const [currentResult, setCurrentResult] = useState<any | null>(null);

  useEffect(() => {
    if (isOpen && !currentResult) {
      handleRunOptimization();
    }
  }, [isOpen]);

  const handleRunOptimization = async () => {
    setIsLoading(true);
    setError(null);

    const payload = {
      tenant_id: "tenant_default",
      workspace_id: "workspace_default",
      plant_id: plantId,
      problem_name: problemName,
      description: "Deterministic capacity and supplier allocation balancing throughput, risk, and emissions.",
      decision_scope: decisionScope,
      method: solverMethod,
      multi_objective_method: multiObjMethod,
      variables: [
        {
          variable_id: "ALLOC_LINE_A",
          name: "Line A Production Rate",
          variable_type: "ALLOCATE_CAPACITY",
          domain: {
            domain_type: "BOUNDED_SCALAR",
            min_value: 0.0,
            max_value: 500.0,
            step: 50.0,
          },
          unit: "UNITS_PER_DAY",
        },
        {
          variable_id: "ALLOC_LINE_B",
          name: "Line B Production Rate",
          variable_type: "ALLOCATE_CAPACITY",
          domain: {
            domain_type: "BOUNDED_SCALAR",
            min_value: 0.0,
            max_value: 450.0,
            step: 50.0,
          },
          unit: "UNITS_PER_DAY",
        },
        {
          variable_id: "ALLOC_SUPPLIER_PRIMARY",
          name: "Primary Supplier Allocation",
          variable_type: "ASSIGN_SUPPLIER",
          domain: {
            domain_type: "BOUNDED_SCALAR",
            min_value: 0.0,
            max_value: 400.0,
            step: 50.0,
          },
          unit: "UNITS_PER_DAY",
        },
      ],
      objectives: [
        {
          objective_id: "OBJ_MIN_COST",
          name: "Operational Cost",
          objective_type: "MINIMIZE_COST",
          direction: "MINIMIZE",
          weight: 0.40,
          unit: "INR",
          weight_source: "ENTERPRISE_POLICY",
          normalization: "MIN_MAX",
          order: 1,
        },
        {
          objective_id: "OBJ_MIN_RISK",
          name: "Supplier & Failure Risk",
          objective_type: "MINIMIZE_RISK",
          direction: "MINIMIZE",
          weight: 0.35,
          unit: "INDEX",
          weight_source: "ENTERPRISE_POLICY",
          normalization: "MIN_MAX",
          order: 2,
        },
        {
          objective_id: "OBJ_MIN_EMISSIONS",
          name: "Carbon Emissions",
          objective_type: "MINIMIZE_EMISSIONS",
          direction: "MINIMIZE",
          weight: 0.25,
          unit: "KG_CO2E",
          weight_source: "SUSTAINABILITY_POLICY",
          normalization: "MIN_MAX",
          order: 3,
        },
      ],
      constraints: [
        {
          constraint_id: "C_DEMAND_SATISFACTION",
          name: "Total Demand Satisfaction",
          constraint_type: "DEMAND",
          operator: ">=",
          left_expression: "SUM_ALLOCATION",
          right_expression: 800.0,
          unit: "UNITS",
          hard_or_soft: "HARD",
          source: "CUSTOMER_COMMITMENT",
        },
        {
          constraint_id: "C_LINE_A_MAX",
          name: "Line A Maximum Capacity",
          constraint_type: "CAPACITY",
          operator: "<=",
          left_expression: "ALLOC_LINE_A",
          right_expression: 500.0,
          unit: "UNITS",
          hard_or_soft: "HARD",
          source: "EQUIPMENT_SPECIFICATION",
        },
        {
          constraint_id: "C_SUPPLIER_RELIABILITY",
          name: "Preferred Supplier Share",
          constraint_type: "SUPPLIER_CAPACITY",
          operator: ">=",
          left_expression: "ALLOC_SUPPLIER_PRIMARY",
          right_expression: 200.0,
          unit: "UNITS",
          hard_or_soft: "SOFT",
          penalty_weight: 50.0,
          source: "SUPPLY_CHAIN_POLICY",
        },
      ],
      context: {
        simulation_id: "sim_counterfactual_demand_surge",
        forecast_reference: "fc_demand_q4_horizon",
        supplier_risk_reference: "sup_risk_tier1_composite",
        digital_twin_reference: "twin_state_plant01_active",
        context_parameters: {
          ALLOC_LINE_A_unit_cost: 12.0,
          ALLOC_LINE_B_unit_cost: 15.0,
          ALLOC_SUPPLIER_PRIMARY_unit_cost: 11.0,
          ALLOC_LINE_A_risk_score: 0.20,
          ALLOC_LINE_B_risk_score: 0.15,
          ALLOC_SUPPLIER_PRIMARY_risk_score: 0.45,
          ALLOC_LINE_A_emission_factor: 0.08,
          ALLOC_LINE_B_emission_factor: 0.04,
          ALLOC_SUPPLIER_PRIMARY_emission_factor: 0.06,
          target_demand: 800.0,
          total_capacity: 950.0,
        },
      },
    };

    try {
      const res = await api.analyzeOptimization(payload);
      if (res) {
        setCurrentResult(res);
      } else {
        setError("Failed to run optimization analysis.");
      }
    } catch (err: any) {
      setError(err?.message || "Error running optimization");
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) return null;

  const recommended = currentResult?.recommended_solution;
  const feasibility = currentResult?.feasibility;
  const problem = currentResult?.problem;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4">
      <div className="relative w-full max-w-6xl h-[92vh] bg-slate-900 border border-emerald-500/30 rounded-xl shadow-2xl flex flex-col overflow-hidden text-slate-100 font-sans">
        
        {/* HEADER / GOVERNED BOUNDARY NOTICE */}
        <div className="px-6 py-4 border-b border-slate-800 bg-slate-950/80 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <span className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 font-mono text-xs font-bold">
              OPT-V3
            </span>
            <div>
              <h2 className="text-lg font-bold tracking-wide flex items-center space-x-2">
                <span>Optimization Intelligence Foundation</span>
                <span className="text-xs px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-300 border border-blue-500/30 font-mono">
                  {currentResult?.optimality_status || "ANALYZING"}
                </span>
              </h2>
              <p className="text-xs text-slate-400">
                Governed Analytical Decision Support • Multi-Objective Pareto & Trade-Offs
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-4">
            <button
              onClick={handleRunOptimization}
              disabled={isLoading}
              className="px-3 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 text-xs font-semibold tracking-wider text-white transition disabled:opacity-50"
            >
              {isLoading ? "Optimizing..." : "Re-Analyze"}
            </button>
            <button
              onClick={onClose}
              className="text-slate-400 hover:text-white text-sm px-2 py-1 transition"
            >
              ✕
            </button>
          </div>
        </div>

        {/* MANDATORY ARCHITECTURAL BANNER (Section 45, 46) */}
        <div className="bg-amber-950/40 border-b border-amber-500/30 px-6 py-2 flex items-center justify-between text-xs font-mono text-amber-300">
          <div className="flex items-center space-x-2">
            <span className="font-bold tracking-widest bg-amber-500/20 px-2 py-0.5 rounded border border-amber-500/40">
              OPTIMIZATION
            </span>
            <span className="font-bold tracking-widest bg-blue-500/20 px-2 py-0.5 rounded border border-blue-500/40 text-blue-300">
              ANALYTICAL RECOMMENDATION
            </span>
            <span className="font-bold tracking-widest bg-rose-500/20 px-2 py-0.5 rounded border border-rose-500/40 text-rose-300">
              NOT EXECUTED
            </span>
          </div>
          <span className="text-[11px] text-amber-200/70">
            Produces non-executing decision intelligence. Requires authorized operational review.
          </span>
        </div>

        {/* TABS NAVIGATION */}
        <div className="flex border-b border-slate-800 bg-slate-950/50 px-6 space-x-1 text-xs font-medium">
          {[
            { id: "results", label: "Recommended Plan" },
            { id: "problem", label: "Decision Scope & Variables" },
            { id: "objectives", label: "Objectives & Weights" },
            { id: "constraints", label: "Constraints & Margins" },
            { id: "tradeoffs", label: "Trade-offs & Alternatives" },
            { id: "sensitivity", label: "Sensitivity & Robustness" },
            { id: "evidence", label: "Evidence & Limitations" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`px-4 py-3 border-b-2 transition ${
                activeTab === tab.id
                  ? "border-emerald-500 text-emerald-400 bg-emerald-500/5 font-semibold"
                  : "border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/20"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* MODAL BODY */}
        <div className="flex-1 overflow-y-auto p-6 space-x-0 space-y-6 bg-slate-900/60">
          {error && (
            <div className="p-4 rounded-lg bg-rose-950/40 border border-rose-500/40 text-rose-200 text-sm">
              {error}
            </div>
          )}

          {/* TAB 1: RECOMMENDED PLAN */}
          {activeTab === "results" && (
            <div className="space-y-6">
              {/* Summary Metrics */}
              <div className="grid grid-cols-4 gap-4">
                <div className="p-4 rounded-lg bg-slate-800/40 border border-slate-700/50">
                  <span className="text-xs text-slate-400 block font-mono">OPTIMALITY STATUS</span>
                  <span className="text-lg font-bold text-emerald-400 font-mono">
                    {currentResult?.optimality_status || "UNKNOWN"}
                  </span>
                  <span className="text-[11px] text-slate-500 block mt-1">
                    Solver: {currentResult?.solver_metadata?.solver_name || "Deterministic"}
                  </span>
                </div>

                <div className="p-4 rounded-lg bg-slate-800/40 border border-slate-700/50">
                  <span className="text-xs text-slate-400 block font-mono">FEASIBILITY</span>
                  <span className={`text-lg font-bold font-mono ${feasibility?.is_feasible ? "text-emerald-400" : "text-rose-400"}`}>
                    {feasibility?.status || "UNKNOWN"}
                  </span>
                  <span className="text-[11px] text-slate-500 block mt-1">
                    {feasibility?.blocking_constraints?.length || 0} blocking constraints
                  </span>
                </div>

                <div className="p-4 rounded-lg bg-slate-800/40 border border-slate-700/50">
                  <span className="text-xs text-slate-400 block font-mono">ROBUSTNESS</span>
                  <span className={`text-lg font-bold font-mono ${
                    currentResult?.robustness === "ROBUST" ? "text-emerald-400" : "text-amber-400"
                  }`}>
                    {currentResult?.robustness || "UNKNOWN"}
                  </span>
                  <span className="text-[11px] text-slate-500 block mt-1">Under ±10% parameter shifts</span>
                </div>

                <div className="p-4 rounded-lg bg-slate-800/40 border border-slate-700/50">
                  <span className="text-xs text-slate-400 block font-mono">CONFIDENCE</span>
                  <span className="text-lg font-bold text-blue-400 font-mono">
                    {currentResult?.confidence || "HIGH"}
                  </span>
                  <span className="text-[11px] text-slate-500 block mt-1">Grounded in observed twin & forecast</span>
                </div>
              </div>

              {/* Recommended Decision Values */}
              <div className="p-5 rounded-lg bg-slate-950/60 border border-emerald-500/30">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-bold text-emerald-400 uppercase tracking-wider font-mono">
                    Recommended Candidate Decisions ({recommended?.candidate_id || "None"})
                  </h3>
                  <span className="text-xs px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 font-mono">
                    Composite Score: {recommended?.score ?? "N/A"}
                  </span>
                </div>

                {recommended?.decision_values ? (
                  <div className="grid grid-cols-3 gap-3">
                    {Object.entries(recommended.decision_values).map(([k, v]) => (
                      <div key={k} className="p-3 bg-slate-900/80 rounded border border-slate-800">
                        <span className="text-xs text-slate-400 font-mono block">{k}</span>
                        <span className="text-base font-bold text-slate-100 font-mono">
                          {String(v)}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-slate-400">No feasible candidate discovered.</p>
                )}
              </div>

              {/* Objective Breakdown & Structured Explanation */}
              <div className="grid grid-cols-2 gap-4">
                <div className="p-4 rounded-lg bg-slate-950/60 border border-slate-800">
                  <h4 className="text-xs font-bold text-slate-300 font-mono uppercase tracking-wider mb-3">
                    Objective Values
                  </h4>
                  <div className="space-y-2">
                    {recommended?.objective_values && Object.entries(recommended.objective_values).map(([k, v]) => (
                      <div key={k} className="flex justify-between text-xs py-1.5 border-b border-slate-800/60 font-mono">
                        <span className="text-slate-400">{k}</span>
                        <span className="text-slate-200 font-bold">{String(v)}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="p-4 rounded-lg bg-slate-950/60 border border-slate-800">
                  <h4 className="text-xs font-bold text-slate-300 font-mono uppercase tracking-wider mb-3">
                    Structured Explanation (Non-LLM)
                  </h4>
                  <ul className="space-y-2 text-xs text-slate-300 list-disc list-inside">
                    {currentResult?.explanation?.why_selected?.map((reason: string, i: number) => (
                      <li key={i}>{reason}</li>
                    )) || <li>Evaluating optimal boundary conditions...</li>}
                  </ul>
                  {currentResult?.explanation?.binding_constraints?.length > 0 && (
                    <div className="mt-3 pt-3 border-t border-slate-800 text-xs">
                      <span className="text-slate-400 font-mono">Binding Constraints: </span>
                      <span className="text-amber-400 font-mono">
                        {currentResult.explanation.binding_constraints.join(", ")}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: PROBLEM & VARIABLES */}
          {activeTab === "problem" && (
            <div className="space-y-4">
              <div className="p-4 rounded-lg bg-slate-950/60 border border-slate-800 flex justify-between text-xs font-mono">
                <div>
                  <span className="text-slate-400 block">DECISION SCOPE</span>
                  <span className="text-slate-200 font-bold">{problem?.decision_scope}</span>
                </div>
                <div>
                  <span className="text-slate-400 block">HORIZON</span>
                  <span className="text-slate-200 font-bold">{problem?.horizon}</span>
                </div>
                <div>
                  <span className="text-slate-400 block">FINGERPRINT (SHA-256)</span>
                  <span className="text-slate-400 font-mono">{currentResult?.input_fingerprint?.slice(0, 16)}...</span>
                </div>
              </div>

              <div className="rounded-lg border border-slate-800 overflow-hidden">
                <table className="w-full text-left text-xs font-mono">
                  <thead className="bg-slate-950/80 text-slate-400 uppercase tracking-wider border-b border-slate-800">
                    <tr>
                      <th className="p-3">Variable ID</th>
                      <th className="p-3">Name</th>
                      <th className="p-3">Type</th>
                      <th className="p-3">Domain</th>
                      <th className="p-3">Bounds [Min, Max]</th>
                      <th className="p-3">Unit</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 text-slate-300">
                    {problem?.variables?.map((v: any) => (
                      <tr key={v.variable_id} className="hover:bg-slate-800/20">
                        <td className="p-3 font-bold text-emerald-400">{v.variable_id}</td>
                        <td className="p-3">{v.name}</td>
                        <td className="p-3 text-slate-400">{v.variable_type}</td>
                        <td className="p-3">{v.domain.domain_type}</td>
                        <td className="p-3 text-slate-200">
                          [{v.domain.min_value ?? "-∞"}, {v.domain.max_value ?? "+∞"}]
                        </td>
                        <td className="p-3 text-slate-400">{v.unit || "N/A"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB 3: OBJECTIVES */}
          {activeTab === "objectives" && (
            <div className="rounded-lg border border-slate-800 overflow-hidden">
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-slate-950/80 text-slate-400 uppercase tracking-wider border-b border-slate-800">
                  <tr>
                    <th className="p-3">Objective ID</th>
                    <th className="p-3">Name</th>
                    <th className="p-3">Type</th>
                    <th className="p-3">Direction</th>
                    <th className="p-3">Weight</th>
                    <th className="p-3">Weight Source</th>
                    <th className="p-3">Unit</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 text-slate-300">
                  {problem?.objectives?.map((obj: any) => (
                    <tr key={obj.objective_id} className="hover:bg-slate-800/20">
                      <td className="p-3 font-bold text-blue-400">{obj.objective_id}</td>
                      <td className="p-3">{obj.name}</td>
                      <td className="p-3 text-slate-400">{obj.objective_type}</td>
                      <td className="p-3">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          obj.direction === "MINIMIZE" ? "bg-cyan-500/20 text-cyan-300" : "bg-emerald-500/20 text-emerald-300"
                        }`}>
                          {obj.direction}
                        </span>
                      </td>
                      <td className="p-3 font-bold text-slate-100">{obj.weight}</td>
                      <td className="p-3 text-slate-400">{obj.weight_source}</td>
                      <td className="p-3 text-slate-400">{obj.unit || "N/A"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* TAB 4: CONSTRAINTS */}
          {activeTab === "constraints" && (
            <div className="rounded-lg border border-slate-800 overflow-hidden">
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-slate-950/80 text-slate-400 uppercase tracking-wider border-b border-slate-800">
                  <tr>
                    <th className="p-3">Constraint ID</th>
                    <th className="p-3">Name</th>
                    <th className="p-3">Class</th>
                    <th className="p-3">Expression</th>
                    <th className="p-3">Status</th>
                    <th className="p-3">Margin</th>
                    <th className="p-3">Penalty</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 text-slate-300">
                  {recommended?.constraint_results?.map((cr: any) => (
                    <tr key={cr.constraint_id} className="hover:bg-slate-800/20">
                      <td className="p-3 font-bold text-slate-200">{cr.constraint_id}</td>
                      <td className="p-3">{cr.name}</td>
                      <td className="p-3">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          cr.hard_or_soft === "HARD" ? "bg-rose-500/20 text-rose-300" : "bg-amber-500/20 text-amber-300"
                        }`}>
                          {cr.hard_or_soft}
                        </span>
                      </td>
                      <td className="p-3 text-slate-400">
                        {cr.observed_value ?? "N/A"} / {cr.threshold_value ?? "N/A"}
                      </td>
                      <td className="p-3">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          cr.satisfied ? (cr.is_binding ? "bg-amber-500/20 text-amber-300" : "bg-emerald-500/20 text-emerald-300") : "bg-rose-500/20 text-rose-300"
                        }`}>
                          {cr.satisfied ? (cr.is_binding ? "BINDING" : "SATISFIED") : "VIOLATED"}
                        </span>
                      </td>
                      <td className="p-3 text-slate-200">{cr.margin ?? "N/A"}</td>
                      <td className="p-3 text-slate-400">{cr.penalty || "0.0"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* TAB 5: TRADEOFFS & ALTERNATIVES */}
          {activeTab === "tradeoffs" && (
            <div className="space-y-4">
              <h3 className="text-xs font-bold text-slate-300 font-mono uppercase tracking-wider">
                Multi-Candidate Trade-Off Assessments
              </h3>
              {currentResult?.tradeoffs?.length > 0 ? (
                currentResult.tradeoffs.map((t: any, i: number) => (
                  <div key={i} className="p-4 rounded-lg bg-slate-950/60 border border-slate-800 space-y-3 text-xs">
                    <div className="flex justify-between items-center border-b border-slate-800 pb-2">
                      <span className="font-mono text-emerald-400 font-bold">
                        {t.compared_candidate_id} vs Recommended
                      </span>
                      <span className="text-slate-400">{t.tradeoff_summary}</span>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-1">
                        <span className="text-[11px] font-mono text-emerald-400 font-bold block">ADVANTAGES</span>
                        {t.advantages?.map((adv: string, j: number) => (
                          <div key={j} className="text-slate-300">• {adv}</div>
                        )) || <div className="text-slate-500">None</div>}
                      </div>
                      <div className="space-y-1">
                        <span className="text-[11px] font-mono text-rose-400 font-bold block">TRADE-OFF DISADVANTAGES</span>
                        {t.disadvantages?.map((dis: string, j: number) => (
                          <div key={j} className="text-slate-300">• {dis}</div>
                        )) || <div className="text-slate-500">None</div>}
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <div className="p-6 text-center text-xs text-slate-500 font-mono">
                  Only one feasible candidate found under current hard constraints.
                </div>
              )}
            </div>
          )}

          {/* TAB 6: SENSITIVITY & ROBUSTNESS */}
          {activeTab === "sensitivity" && (
            <div className="space-y-4">
              <div className="p-4 rounded-lg bg-slate-950/60 border border-slate-800 flex justify-between items-center text-xs font-mono">
                <div>
                  <span className="text-slate-400 block">ROBUSTNESS ASSESSMENT</span>
                  <span className={`text-base font-bold ${
                    currentResult?.robustness === "ROBUST" ? "text-emerald-400" : "text-amber-400"
                  }`}>
                    {currentResult?.robustness}
                  </span>
                </div>
                <p className="text-slate-400 max-w-lg text-right">
                  Controlled parameter shifts (+5%, +10%, -5%, -10%) tested against recommended allocation to evaluate feasibility survival.
                </p>
              </div>

              <div className="rounded-lg border border-slate-800 overflow-hidden">
                <table className="w-full text-left text-xs font-mono">
                  <thead className="bg-slate-950/80 text-slate-400 uppercase tracking-wider border-b border-slate-800">
                    <tr>
                      <th className="p-3">Parameter</th>
                      <th className="p-3">Shift %</th>
                      <th className="p-3">Baseline</th>
                      <th className="p-3">Perturbed</th>
                      <th className="p-3">Objective Delta</th>
                      <th className="p-3">Feasibility Preserved</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 text-slate-300">
                    {currentResult?.sensitivity_analysis?.map((s: any, i: number) => (
                      <tr key={i} className="hover:bg-slate-800/20">
                        <td className="p-3 font-bold text-slate-200">{s.parameter}</td>
                        <td className="p-3">{s.perturbation_pct > 0 ? `+${s.perturbation_pct}%` : `${s.perturbation_pct}%`}</td>
                        <td className="p-3 text-slate-400">{s.baseline_value}</td>
                        <td className="p-3 text-slate-200">{s.changed_value}</td>
                        <td className="p-3 text-slate-300">{s.objective_delta}</td>
                        <td className="p-3">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            s.feasibility_maintained ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300"
                          }`}>
                            {s.feasibility_maintained ? "MAINTAINED" : "VIOLATED"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB 7: EVIDENCE & LIMITATIONS */}
          {activeTab === "evidence" && (
            <div className="space-y-4">
              <h3 className="text-xs font-bold text-slate-300 font-mono uppercase tracking-wider">
                Upstream Intelligence Evidence Chain
              </h3>
              <div className="space-y-3">
                {currentResult?.evidence?.map((ev: any) => (
                  <div key={ev.evidence_id} className="p-4 rounded-lg bg-slate-950/60 border border-slate-800 text-xs font-mono space-y-1">
                    <div className="flex justify-between items-center">
                      <span className="font-bold text-blue-400">{ev.source_type}: {ev.source_id}</span>
                      <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]">
                        {ev.provenance} • {ev.confidence} CONFIDENCE
                      </span>
                    </div>
                    <p className="text-slate-300 font-sans text-xs pt-1">{ev.explanation}</p>
                  </div>
                ))}
              </div>

              {currentResult?.limitations?.length > 0 && (
                <div className="pt-4 border-t border-slate-800 space-y-2">
                  <h4 className="text-xs font-bold text-amber-400 font-mono uppercase tracking-wider">
                    Documented Analytical Limitations
                  </h4>
                  {currentResult.limitations.map((lim: any) => (
                    <div key={lim.limitation_id} className="p-3 rounded bg-amber-950/20 border border-amber-500/20 text-xs text-amber-200/90 font-sans">
                      <span className="font-bold font-mono text-amber-400">{lim.category}: </span>
                      {lim.description}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* FOOTER — STRICTLY NON-EXECUTING */}
        <div className="px-6 py-3 border-t border-slate-800 bg-slate-950/80 flex items-center justify-between text-xs text-slate-400 font-mono">
          <div>
            Optimization Problem ID: <span className="text-slate-300">{problem?.problem_id || "N/A"}</span>
          </div>
          <div className="flex items-center space-x-3">
            <span className="text-slate-500">Decision support advisory only. No operational command dispatched.</span>
            <button
              onClick={onClose}
              className="px-4 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200 transition"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
