"use client";

/**
 * frontend/app/components/WhatIfSimulationModal.tsx
 *
 * SageCommand V3 — What-If Simulation Intelligence Modal (Prompt 28)
 *
 * ANALYTICAL ONLY — This component allows operators and analysts to construct
 * deterministic counterfactual scenarios, simulate hypothetical states,
 * inspect deltas and downstream impacts, and review auditable evidence.
 * It contains NO actuator controls, execution gateways, PLC commands,
 * work order creation, or operational mutation triggers.
 */

import React, { useState, useEffect } from "react";
import * as api from "../../lib/api";

interface WhatIfSimulationModalProps {
  isOpen: boolean;
  onClose: () => void;
  entityId?: string;
  plantId?: string;
}

interface ScenarioVariableInput {
  variable_id: string;
  variable_type: string;
  parameter_name: string;
  change_type: string;
  value: number;
  unit: string;
}

interface ScenarioConstraintInput {
  constraint_id: string;
  constraint_type: string;
  metric_name: string;
  operator: string;
  threshold_value: number;
  unit: string;
}

export default function WhatIfSimulationModal({
  isOpen,
  onClose,
  entityId = "MCH-01",
  plantId = "PLANT-01",
}: WhatIfSimulationModalProps) {
  const [activeTab, setActiveTab] = useState<"builder" | "results" | "impacts" | "constraints" | "evidence">("builder");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Scenario Builder State
  const [scenarioName, setScenarioName] = useState("Supply Chain Disruption & Demand Surge");
  const [targetEntityId, setTargetEntityId] = useState(entityId);
  const [targetEntityType, setTargetEntityType] = useState("MACHINE");
  const [horizon, setHorizon] = useState("P7D");

  const [variables, setVariables] = useState<ScenarioVariableInput[]>([
    {
      variable_id: "VAR-01",
      variable_type: "DEMAND_CHANGE",
      parameter_name: "demand_rate",
      change_type: "PERCENT_DELTA",
      value: 20.0,
      unit: "PERCENT",
    },
    {
      variable_id: "VAR-02",
      variable_type: "ASSET_AVAILABILITY_CHANGE",
      parameter_name: "asset_availability",
      change_type: "PERCENT_DELTA",
      value: -10.0,
      unit: "PERCENT",
    },
    {
      variable_id: "VAR-03",
      variable_type: "ENERGY_CONSUMPTION_CHANGE",
      parameter_name: "energy_consumption",
      change_type: "PERCENT_DELTA",
      value: 15.0,
      unit: "PERCENT",
    },
  ]);

  const [constraints, setConstraints] = useState<ScenarioConstraintInput[]>([
    {
      constraint_id: "C-01",
      constraint_type: "MAX_CAPACITY",
      metric_name: "capacity_gap",
      operator: "LTE",
      threshold_value: 0.0,
      unit: "UNITS",
    },
    {
      constraint_id: "C-02",
      constraint_type: "SLA_THRESHOLD",
      metric_name: "sla_compliance_rate",
      operator: "GTE",
      threshold_value: 0.95,
      unit: "RATE",
    },
    {
      constraint_id: "C-03",
      constraint_type: "ASSET_AVAILABILITY",
      metric_name: "asset_availability",
      operator: "GTE",
      threshold_value: 0.90,
      unit: "RATIO",
    },
  ]);

  // Simulation Result State
  const [currentResult, setCurrentResult] = useState<any | null>(null);

  useEffect(() => {
    if (isOpen && !currentResult) {
      handleRunSimulation();
    }
  }, [isOpen]);

  const handleAddVariable = () => {
    const nextId = `VAR-${String(variables.length + 1).padStart(2, "0")}`;
    setVariables([
      ...variables,
      {
        variable_id: nextId,
        variable_type: "CUSTOM_SCALAR_CHANGE",
        parameter_name: "production_capacity",
        change_type: "PERCENT_DELTA",
        value: 10.0,
        unit: "PERCENT",
      },
    ]);
  };

  const handleRemoveVariable = (index: number) => {
    setVariables(variables.filter((_, i) => i !== index));
  };

  const handleVariableChange = (index: number, field: string, value: any) => {
    const updated = [...variables];
    (updated[index] as any)[field] = field === "value" ? parseFloat(value) || 0 : value;
    setVariables(updated);
  };

  const handleRunSimulation = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const payload = {
        tenant_id: "tenant_default",
        workspace_id: "workspace_default",
        plant_id: plantId,
        scenario_name: scenarioName,
        description: "Counterfactual simulation generated from What-If Command Center.",
        targets: [
          {
            entity_id: targetEntityId,
            entity_type: targetEntityType,
            target_scope: "ENTITY",
          },
        ],
        variables: variables.map((v) => ({
          variable_id: v.variable_id,
          variable_type: v.variable_type,
          target_entity_id: targetEntityId,
          parameter_name: v.parameter_name,
          change_type: v.change_type,
          value: v.value,
          unit: v.unit,
        })),
        constraints: constraints.map((c) => ({
          constraint_id: c.constraint_id,
          constraint_type: c.constraint_type,
          target_entity_id: targetEntityId,
          metric_name: c.metric_name,
          operator: c.operator,
          threshold_value: c.threshold_value,
          unit: c.unit,
        })),
        horizon: horizon,
        max_propagation_depth: 5,
      };

      const result = await api.analyzeWhatIfSimulation(payload);
      setCurrentResult(result);
    } catch (err: any) {
      setError(err?.message || "Failed to execute What-If simulation.");
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/85 backdrop-blur-md flex items-center justify-center p-4">
      <div className="bg-[#0b0f19] border border-cyan-500/30 rounded-xl w-full max-w-6xl max-h-[92vh] flex flex-col shadow-2xl overflow-hidden font-mono text-gray-200">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-white/[0.02]">
          <div className="flex items-center gap-3">
            <span className="w-3 h-3 rounded-full bg-cyan-400 animate-pulse shadow-[0_0_8px_rgba(34,211,238,0.8)]" />
            <div>
              <h2 className="text-sm font-bold tracking-wider text-cyan-400 uppercase">
                What-If Simulation Intelligence // V3 Counterfactual Engine
              </h2>
              <p className="text-[10px] text-gray-400 tracking-wide">
                Target: {targetEntityId} | Plant: {plantId} | Analytical Model: DETERMINISTIC_COMPOSITE
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="px-2.5 py-1 text-[10px] uppercase font-bold tracking-wider rounded bg-amber-500/10 text-amber-400 border border-amber-500/30">
              Analytical Only — Non-Executing
            </span>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-white text-lg px-2 py-0.5 rounded hover:bg-white/10 transition"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Navigation Tabs */}
        <div className="flex border-b border-white/10 bg-black/40 px-6 gap-2 text-xs">
          {[
            { id: "builder", label: "Scenario Builder" },
            { id: "results", label: "Deltas & State" },
            { id: "impacts", label: "Downstream Impacts" },
            { id: "constraints", label: "Constraints & Limits" },
            { id: "evidence", label: "Evidence Chain" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`py-3 px-4 border-b-2 font-medium tracking-wide transition ${
                activeTab === tab.id
                  ? "border-cyan-400 text-cyan-400 bg-cyan-500/10"
                  : "border-transparent text-gray-400 hover:text-gray-200 hover:bg-white/5"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {error && (
            <div className="p-3 bg-red-950/50 border border-red-500/40 rounded text-red-300 text-xs">
              ⚠️ {error}
            </div>
          )}

          {/* TAB 1: SCENARIO BUILDER */}
          {activeTab === "builder" && (
            <div className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 bg-white/[0.02] p-4 rounded-lg border border-white/5">
                <div>
                  <label className="text-[11px] text-gray-400 uppercase tracking-wider block mb-1">Scenario Title</label>
                  <input
                    type="text"
                    value={scenarioName}
                    onChange={(e) => setScenarioName(e.target.value)}
                    className="w-full bg-black/50 border border-white/10 rounded px-3 py-1.5 text-xs text-cyan-300 focus:border-cyan-400 outline-none"
                  />
                </div>
                <div>
                  <label className="text-[11px] text-gray-400 uppercase tracking-wider block mb-1">Target Entity ID</label>
                  <input
                    type="text"
                    value={targetEntityId}
                    onChange={(e) => setTargetEntityId(e.target.value)}
                    className="w-full bg-black/50 border border-white/10 rounded px-3 py-1.5 text-xs text-cyan-300 focus:border-cyan-400 outline-none"
                  />
                </div>
                <div>
                  <label className="text-[11px] text-gray-400 uppercase tracking-wider block mb-1">Simulation Horizon</label>
                  <select
                    value={horizon}
                    onChange={(e) => setHorizon(e.target.value)}
                    className="w-full bg-black/50 border border-white/10 rounded px-3 py-1.5 text-xs text-cyan-300 focus:border-cyan-400 outline-none"
                  >
                    <option value="P1D">24 Hours (P1D)</option>
                    <option value="P7D">7 Days (P7D)</option>
                    <option value="P30D">30 Days (P30D)</option>
                  </select>
                </div>
              </div>

              {/* Variable Builder */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-bold text-cyan-400 tracking-wider uppercase">
                    Hypothetical Scenario Variables ({variables.length})
                  </h3>
                  <button
                    onClick={handleAddVariable}
                    className="px-2.5 py-1 text-[11px] bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 rounded hover:bg-cyan-500/30 transition"
                  >
                    + Add Variable
                  </button>
                </div>

                <div className="space-y-2">
                  {variables.map((v, idx) => (
                    <div
                      key={v.variable_id}
                      className="grid grid-cols-12 gap-2 bg-black/40 border border-white/10 p-3 rounded items-center text-xs"
                    >
                      <div className="col-span-2 text-cyan-400 font-bold">{v.variable_id}</div>
                      <div className="col-span-3">
                        <select
                          value={v.variable_type}
                          onChange={(e) => handleVariableChange(idx, "variable_type", e.target.value)}
                          className="w-full bg-black/70 border border-white/10 rounded px-2 py-1 text-[11px]"
                        >
                          <option value="DEMAND_CHANGE">Demand Change</option>
                          <option value="SUPPLY_CAPACITY_CHANGE">Supplier Capacity</option>
                          <option value="ASSET_AVAILABILITY_CHANGE">Asset Availability</option>
                          <option value="ASSET_DEGRADATION_CHANGE">Asset Degradation</option>
                          <option value="ENERGY_CONSUMPTION_CHANGE">Energy Consumption</option>
                          <option value="LEAD_TIME_CHANGE">Lead Time Change</option>
                          <option value="QUALITY_RATE_CHANGE">Quality Rate Change</option>
                          <option value="CUSTOM_SCALAR_CHANGE">Custom Parameter</option>
                        </select>
                      </div>
                      <div className="col-span-3">
                        <input
                          type="text"
                          value={v.parameter_name}
                          onChange={(e) => handleVariableChange(idx, "parameter_name", e.target.value)}
                          className="w-full bg-black/70 border border-white/10 rounded px-2 py-1 text-[11px]"
                          placeholder="metric_name"
                        />
                      </div>
                      <div className="col-span-2">
                        <input
                          type="number"
                          value={v.value}
                          onChange={(e) => handleVariableChange(idx, "value", e.target.value)}
                          className="w-full bg-black/70 border border-white/10 rounded px-2 py-1 text-[11px] text-amber-300 font-mono"
                        />
                      </div>
                      <div className="col-span-1 text-[10px] text-gray-400">{v.change_type}</div>
                      <div className="col-span-1 text-right">
                        <button
                          onClick={() => handleRemoveVariable(idx)}
                          className="text-red-400 hover:text-red-300 text-xs px-2"
                        >
                          ✕
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Action Trigger */}
              <div className="pt-4 flex justify-end gap-3 border-t border-white/10">
                <button
                  onClick={handleRunSimulation}
                  disabled={isLoading}
                  className="px-6 py-2.5 bg-cyan-500 text-black font-bold text-xs uppercase tracking-wider rounded hover:bg-cyan-400 transition disabled:opacity-50 shadow-[0_0_15px_rgba(6,182,212,0.4)]"
                >
                  {isLoading ? "Simulating Counterfactual State..." : "Execute What-If Analysis"}
                </button>
              </div>
            </div>
          )}

          {/* TAB 2: DELTAS & STATE */}
          {activeTab === "results" && (
            <div className="space-y-6">
              {currentResult ? (
                <>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="p-3 bg-white/[0.02] border border-white/10 rounded">
                      <div className="text-[10px] text-gray-400 uppercase">Baseline Source</div>
                      <div className="text-xs font-bold text-cyan-300 mt-1">{currentResult.baseline.source}</div>
                      <div className="text-[10px] text-gray-500 mt-0.5">{currentResult.baseline.source_id}</div>
                    </div>
                    <div className="p-3 bg-white/[0.02] border border-white/10 rounded">
                      <div className="text-[10px] text-gray-400 uppercase">Confidence</div>
                      <div className="text-xs font-bold text-emerald-400 mt-1">{currentResult.confidence}</div>
                      <div className="text-[10px] text-gray-500 mt-0.5">Uncertainty: {currentResult.uncertainty.overall_uncertainty}</div>
                    </div>
                    <div className="p-3 bg-white/[0.02] border border-white/10 rounded">
                      <div className="text-[10px] text-gray-400 uppercase">Interaction Effect</div>
                      <div className="text-xs font-bold text-amber-400 mt-1">{currentResult.interaction_effect}</div>
                      <div className="text-[10px] text-gray-500 mt-0.5">{currentResult.variable_contributions.length} variables</div>
                    </div>
                    <div className="p-3 bg-white/[0.02] border border-white/10 rounded">
                      <div className="text-[10px] text-gray-400 uppercase">Data Quality</div>
                      <div className="text-xs font-bold text-cyan-400 mt-1">
                        {((currentResult.data_quality_score || 0.95) * 100).toFixed(1)}%
                      </div>
                      <div className="text-[10px] text-gray-500 mt-0.5">Grounding: OBSERVED</div>
                    </div>
                  </div>

                  {/* Deltas Table */}
                  <div className="border border-white/10 rounded-lg overflow-hidden">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-black/60 text-gray-400 uppercase text-[10px] border-b border-white/10">
                        <tr>
                          <th className="py-2.5 px-4">Metric</th>
                          <th className="py-2.5 px-4">Baseline</th>
                          <th className="py-2.5 px-4">Simulated</th>
                          <th className="py-2.5 px-4">Delta</th>
                          <th className="py-2.5 px-4">Delta %</th>
                          <th className="py-2.5 px-4">Status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5">
                        {currentResult.deltas.map((d: any) => (
                          <tr key={d.metric_name} className="hover:bg-white/[0.02]">
                            <td className="py-2.5 px-4 font-bold text-gray-200">{d.metric_name}</td>
                            <td className="py-2.5 px-4 font-mono text-gray-400">
                              {d.baseline_value !== null ? d.baseline_value : "—"}
                            </td>
                            <td className="py-2.5 px-4 font-mono text-cyan-300 font-bold">
                              {d.simulated_value !== null ? d.simulated_value : "—"}
                            </td>
                            <td className="py-2.5 px-4 font-mono">
                              {d.delta !== null ? (
                                <span className={d.delta > 0 ? "text-amber-400" : d.delta < 0 ? "text-blue-400" : "text-gray-400"}>
                                  {d.delta > 0 ? `+${d.delta}` : d.delta}
                                </span>
                              ) : (
                                "—"
                              )}
                            </td>
                            <td className="py-2.5 px-4 font-mono">
                              {d.delta_percent !== null ? (
                                <span className={d.delta_percent > 0 ? "text-amber-400" : "text-blue-400"}>
                                  {d.delta_percent > 0 ? `+${d.delta_percent}%` : `${d.delta_percent}%`}
                                </span>
                              ) : (
                                "—"
                              )}
                            </td>
                            <td className="py-2.5 px-4">
                              <span
                                className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                  d.classification === "CHANGED"
                                    ? "bg-amber-500/10 text-amber-400 border border-amber-500/30"
                                    : "bg-gray-500/10 text-gray-400"
                                }`}
                              >
                                {d.classification}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <div className="text-center py-12 text-gray-500 text-xs">Run a simulation to view delta metrics.</div>
              )}
            </div>
          )}

          {/* TAB 3: DOWNSTREAM IMPACTS */}
          {activeTab === "impacts" && (
            <div className="space-y-4">
              {currentResult && currentResult.impact_assessments.length > 0 ? (
                currentResult.impact_assessments.map((imp: any) => (
                  <div
                    key={imp.impact_id}
                    className="p-4 bg-black/40 border border-white/10 rounded-lg flex flex-col gap-2"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-cyan-500/10 text-cyan-400 border border-cyan-500/30">
                          {imp.category}
                        </span>
                        <span className="text-xs font-bold text-gray-200">{imp.affected_entity_id}</span>
                      </div>
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          imp.severity === "CRITICAL"
                            ? "bg-red-500/20 text-red-400 border border-red-500/40"
                            : imp.severity === "HIGH"
                            ? "bg-amber-500/20 text-amber-400 border border-amber-500/40"
                            : "bg-blue-500/20 text-blue-400 border border-blue-500/40"
                        }`}
                      >
                        {imp.severity}
                      </span>
                    </div>
                    <p className="text-xs text-gray-300">{imp.description}</p>
                    <div className="flex items-center gap-4 text-[10px] text-gray-500 font-mono mt-1">
                      <span>Hop Distance: {imp.propagation_distance}</span>
                      <span>Confidence: {imp.confidence}</span>
                      <span>Provenance: {imp.provenance}</span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-center py-12 text-gray-500 text-xs">No downstream impacts projected.</div>
              )}
            </div>
          )}

          {/* TAB 4: CONSTRAINTS & LIMITATIONS */}
          {activeTab === "constraints" && (
            <div className="space-y-6">
              {/* Constraints */}
              <div className="space-y-3">
                <h3 className="text-xs font-bold text-cyan-400 tracking-wider uppercase">
                  Constraint Verification
                </h3>
                {currentResult && currentResult.constraint_results.length > 0 ? (
                  currentResult.constraint_results.map((c: any) => (
                    <div
                      key={c.constraint_id}
                      className="p-3 bg-black/40 border border-white/10 rounded flex items-center justify-between"
                    >
                      <div>
                        <div className="text-xs font-bold text-gray-200">{c.metric_name}</div>
                        <div className="text-[11px] text-gray-400 mt-0.5">{c.explanation}</div>
                      </div>
                      <span
                        className={`px-2.5 py-1 rounded text-[10px] font-bold ${
                          c.status === "SATISFIED"
                            ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                            : c.status === "VIOLATED"
                            ? "bg-red-500/10 text-red-400 border border-red-500/30"
                            : "bg-gray-500/10 text-gray-400"
                        }`}
                      >
                        {c.status}
                      </span>
                    </div>
                  ))
                ) : (
                  <div className="text-gray-500 text-xs">No constraints evaluated.</div>
                )}
              </div>

              {/* Limitations */}
              <div className="space-y-3 pt-4 border-t border-white/10">
                <h3 className="text-xs font-bold text-amber-400 tracking-wider uppercase">
                  Explicit Analytical Limitations
                </h3>
                {currentResult && currentResult.limitations.length > 0 ? (
                  currentResult.limitations.map((lim: any) => (
                    <div
                      key={lim.limitation_id}
                      className="p-3 bg-amber-950/20 border border-amber-500/20 rounded text-xs text-amber-200"
                    >
                      <div className="font-bold text-[11px] uppercase tracking-wider text-amber-400">
                        [{lim.category}] {lim.limitation_id}
                      </div>
                      <p className="mt-1 text-[11px] text-gray-300">{lim.description}</p>
                    </div>
                  ))
                ) : (
                  <div className="text-gray-500 text-xs">No material limitations recorded.</div>
                )}
              </div>
            </div>
          )}

          {/* TAB 5: EVIDENCE CHAIN */}
          {activeTab === "evidence" && (
            <div className="space-y-3">
              <div className="p-3 bg-black/50 border border-cyan-500/20 rounded font-mono text-[10px] text-cyan-300 break-all mb-4">
                Deterministic Fingerprint (SHA-256): {currentResult?.input_fingerprint || "—"}
              </div>

              {currentResult && currentResult.evidence.length > 0 ? (
                currentResult.evidence.map((ev: any) => (
                  <div
                    key={ev.evidence_id}
                    className="p-3 bg-black/40 border border-white/10 rounded flex flex-col gap-1 text-xs"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-cyan-400">{ev.evidence_id}</span>
                      <span className="text-[10px] text-gray-500 font-mono">{ev.source_type}</span>
                    </div>
                    <p className="text-gray-300 text-[11px]">{ev.explanation}</p>
                    <div className="flex items-center gap-4 text-[10px] text-gray-500 mt-1">
                      <span>Source ID: {ev.source_id}</span>
                      <span>Relationship: {ev.relationship}</span>
                      <span>Provenance: {ev.provenance}</span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-center py-12 text-gray-500 text-xs">No evidence chain available.</div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-white/10 bg-black/60 flex items-center justify-between text-[11px] text-gray-400">
          <div>
            System: <span className="text-cyan-400">SageCommand V3 Industrial OS</span> | Layer: Counterfactual Intelligence
          </div>
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-white/10 hover:bg-white/15 text-gray-200 rounded text-xs transition"
          >
            Close Window
          </button>
        </div>
      </div>
    </div>
  );
}
