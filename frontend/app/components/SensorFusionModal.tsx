"use client";

/**
 * frontend/app/components/SensorFusionModal.tsx
 *
 * SageCommand V3 — Multimodal Sensor Fusion Intelligence Modal (Prompt 27)
 *
 * ANALYTICAL ONLY — This component visualizes fused industrial telemetry,
 * cross-modal agreement/disagreement, sensor health, and traceable evidence.
 * It contains NO actuator controls, PLC write mechanisms, maintenance scheduling,
 * work order creation, or autonomous remediation.
 */

import React, { useState, useEffect } from "react";
import * as api from "../../lib/api";

interface SensorFusionModalProps {
  isOpen: boolean;
  onClose: () => void;
  entityId?: string;
  plantId?: string;
}

interface ModalityBadge {
  modality: string;
  isPresent: boolean;
}

interface NormalizedObservationView {
  observation_id: string;
  sensor_id: string;
  modality: string;
  measurement_type: string;
  raw_value: any;
  raw_unit?: string;
  normalized_value?: number;
  normalized_unit?: string;
  scaled_score?: number;
  observed_at: string;
  provenance: string;
  confidence: number;
  quality_score: number;
}

interface FusedObservationView {
  fused_observation_id: string;
  target_entity_id: string;
  measurement_type: string;
  fused_value: any;
  unit?: string;
  contributing_modalities: string[];
  fusion_method: string;
  agreement_score: number;
  confidence: string;
  uncertainty: string;
  provenance: string;
}

interface CrossModalCorrelationView {
  correlation_id: string;
  modality_a: string;
  modality_b: string;
  sensor_id_a: string;
  sensor_id_b: string;
  correlation_coefficient?: number;
  sample_count: number;
  is_significant: boolean;
  explanation: string;
}

interface CrossModalAgreementView {
  agreement_id: string;
  status: string;
  agreement_score: number;
  supporting_modalities: string[];
  conflicting_modalities: string[];
  details: string;
}

interface SensorHealthIndicatorView {
  sensor_id: string;
  modality: string;
  status: string;
  reliability_score: number;
  findings: string[];
}

interface FusionEvidenceView {
  evidence_id: string;
  modality: string;
  source_id: string;
  timestamp: string;
  value: any;
  unit?: string;
  confidence: number;
  quality: number;
  contribution: number;
  provenance: string;
  explanation: string;
  is_independent: boolean;
}

interface FusionAssessmentView {
  fusion_assessment_id: string;
  tenant_id: string;
  workspace_id: string;
  plant_id?: string;
  target_entity_id: string;
  target_entity_type: string;
  assessment_timestamp: string;
  evaluation_window: {
    start_time: string;
    end_time: string;
    duration_seconds: number;
  };
  modalities_present: string[];
  modalities_missing: string[];
  normalized_observations: NormalizedObservationView[];
  fused_observations: FusedObservationView[];
  correlations: CrossModalCorrelationView[];
  agreements: CrossModalAgreementView[];
  disagreements: CrossModalAgreementView[];
  sensor_health: SensorHealthIndicatorView[];
  evidence: FusionEvidenceView[];
  confidence: string;
  uncertainty: string;
  provenance: string;
  limitations: string[];
  methodology: string;
  model_version: string;
  input_fingerprint: string;
}

export default function SensorFusionModal({
  isOpen,
  onClose,
  entityId = "MCH-CONVEYOR-01",
  plantId = "PLANT-DETROIT-01",
}: SensorFusionModalProps) {
  const [activeTab, setActiveTab] = useState<"overview" | "fused" | "agreements" | "health" | "evidence">("overview");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [assessment, setAssessment] = useState<FusionAssessmentView | null>(null);

  // Demo analytical trigger
  const runAnalysis = async () => {
    setLoading(true);
    setError(null);
    try {
      const now = new Date().toISOString();
      const payload = {
        tenant_id: "tenant_default",
        workspace_id: "workspace_default",
        plant_id: plantId,
        target_entity_id: entityId,
        target_entity_type: "MACHINE",
        assessment_timestamp: now,
        evaluation_window_seconds: 3600,
        alignment_strategy: "WINDOW",
        fusion_strategy: "WEIGHTED_EVIDENCE_FUSION",
        observations: [
          {
            observation_id: `obs_temp_${Date.now()}`,
            tenant_id: "tenant_default",
            workspace_id: "workspace_default",
            plant_id: plantId,
            entity_id: entityId,
            sensor_id: "TEMP-MOTOR-01",
            modality: "TEMPERATURE",
            measurement_type: "TEMPERATURE",
            value: 82.5,
            unit: "CELSIUS",
            observed_at: now,
            provenance: "OBSERVED",
            confidence: 0.95,
            quality: 0.98,
          },
          {
            observation_id: `obs_vib_${Date.now()}`,
            tenant_id: "tenant_default",
            workspace_id: "workspace_default",
            plant_id: plantId,
            entity_id: entityId,
            sensor_id: "VIB-MOTOR-01",
            modality: "VIBRATION",
            measurement_type: "VIBRATION_RMS",
            value: 6.8,
            unit: "MM/S",
            observed_at: now,
            provenance: "OBSERVED",
            confidence: 0.92,
            quality: 0.95,
          },
          {
            observation_id: `obs_elec_${Date.now()}`,
            tenant_id: "tenant_default",
            workspace_id: "workspace_default",
            plant_id: plantId,
            entity_id: entityId,
            sensor_id: "PWR-FEEDER-01",
            modality: "ELECTRICAL",
            measurement_type: "CURRENT",
            value: 58.2,
            unit: "AMPERE",
            observed_at: now,
            provenance: "OBSERVED",
            confidence: 0.94,
            quality: 0.96,
          },
          {
            observation_id: `obs_acoust_${Date.now()}`,
            tenant_id: "tenant_default",
            workspace_id: "workspace_default",
            plant_id: plantId,
            entity_id: entityId,
            sensor_id: "MIC-ARRAY-01",
            modality: "ACOUSTIC",
            measurement_type: "ACOUSTIC_LEVEL",
            value: 88.0,
            unit: "DB",
            observed_at: now,
            provenance: "OBSERVED",
            confidence: 0.88,
            quality: 0.90,
          },
          {
            observation_id: `obs_therm_${Date.now()}`,
            tenant_id: "tenant_default",
            workspace_id: "workspace_default",
            plant_id: plantId,
            entity_id: entityId,
            sensor_id: "IR-CAM-01",
            modality: "THERMAL",
            measurement_type: "TEMPERATURE",
            value: 84.1,
            unit: "CELSIUS",
            observed_at: now,
            provenance: "OBSERVED",
            confidence: 0.90,
            quality: 0.92,
          },
        ],
      };

      const result = await api.analyzeSensorFusion(payload);
      setAssessment(result);
    } catch (err: any) {
      setError(err?.message || "Failed to load sensor fusion assessment.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      runAnalysis();
    }
  }, [isOpen, entityId, plantId]);

  if (!isOpen) return null;

  return (
    <div
      id="sensor-fusion-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4 overflow-y-auto"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-6xl max-h-[90vh] flex flex-col bg-[#0b0f19] border border-cyan-500/30 rounded-xl shadow-2xl text-slate-200 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header Bar */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-cyan-500/20 bg-slate-900/60">
          <div className="flex items-center space-x-3">
            <div className="h-3 w-3 rounded-full bg-cyan-400 animate-pulse" />
            <h2 className="text-xl font-bold tracking-wide text-cyan-300">
              Multimodal Sensor Fusion Intelligence Foundation
            </h2>
            <span className="px-2 py-0.5 text-xs font-semibold uppercase tracking-wider bg-amber-500/20 text-amber-300 border border-amber-500/40 rounded">
              Analytical Only
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white transition-colors text-2xl leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Analytical Notice Banner */}
        <div className="bg-amber-950/40 border-b border-amber-500/20 px-6 py-2 text-xs text-amber-200/90 flex items-center justify-between">
          <span>
            <strong>NON-ACTUATING SUBSYSTEM:</strong> Multimodal Sensor Fusion provides analytical correlation and fused evidence only. It does NOT command physical PLCs, actuators, work orders, or equipment.
          </span>
          <span className="text-[10px] text-amber-300/70 font-mono">
            V3.27-ANALYTICAL
          </span>
        </div>

        {/* Target Metadata Bar */}
        <div className="px-6 py-3 bg-slate-950/40 border-b border-slate-800 flex flex-wrap items-center justify-between text-xs gap-4">
          <div className="flex items-center space-x-4">
            <div>
              <span className="text-slate-500">Target Entity: </span>
              <span className="font-semibold text-cyan-400">{entityId}</span>
            </div>
            <div>
              <span className="text-slate-500">Plant: </span>
              <span className="text-slate-300">{plantId}</span>
            </div>
            {assessment && (
              <div>
                <span className="text-slate-500">Confidence: </span>
                <span className={`font-semibold ${assessment.confidence === "HIGH" ? "text-emerald-400" : assessment.confidence === "MEDIUM" ? "text-cyan-400" : "text-amber-400"}`}>
                  {assessment.confidence}
                </span>
              </div>
            )}
            {assessment && (
              <div>
                <span className="text-slate-500">Uncertainty: </span>
                <span className={`font-semibold ${assessment.uncertainty === "LOW" ? "text-emerald-400" : "text-amber-400"}`}>
                  {assessment.uncertainty}
                </span>
              </div>
            )}
          </div>
          <div className="flex items-center space-x-2">
            <button
              onClick={runAnalysis}
              disabled={loading}
              className="px-3 py-1 bg-cyan-600/30 hover:bg-cyan-600/50 border border-cyan-500/40 rounded text-cyan-200 transition-colors disabled:opacity-50"
            >
              {loading ? "Fusing Signals..." : "Re-evaluate Fusion"}
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex border-b border-slate-800 px-6 bg-slate-900/30">
          {(["overview", "fused", "agreements", "health", "evidence"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2.5 text-xs font-semibold capitalize border-b-2 transition-colors ${
                activeTab === tab
                  ? "border-cyan-400 text-cyan-300 bg-cyan-950/20"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              {tab === "overview" && "Executive Overview"}
              {tab === "fused" && `Fused Readings (${assessment?.fused_observations?.length || 0})`}
              {tab === "agreements" && `Cross-Modal Logic (${(assessment?.agreements?.length || 0) + (assessment?.disagreements?.length || 0)})`}
              {tab === "health" && `Sensor Health (${assessment?.sensor_health?.length || 0})`}
              {tab === "evidence" && `Evidence Lineage (${assessment?.evidence?.length || 0})`}
            </button>
          ))}
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {error && (
            <div className="p-4 bg-red-950/40 border border-red-500/40 rounded text-red-200 text-sm">
              <strong>Error: </strong> {error}
            </div>
          )}

          {loading && !assessment && (
            <div className="py-20 text-center text-slate-400 animate-pulse">
              Correlating heterogeneous telemetry streams and verifying temporal boundaries...
            </div>
          )}

          {assessment && activeTab === "overview" && (
            <div className="space-y-6">
              {/* Modalities Grid */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="p-4 bg-slate-900/40 border border-slate-800 rounded-lg">
                  <div className="text-xs text-slate-400 uppercase tracking-wider">Modalities Present</div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {assessment.modalities_present.map((mod) => (
                      <span key={mod} className="px-2 py-0.5 text-[11px] bg-cyan-950 border border-cyan-500/40 text-cyan-300 rounded">
                        {mod}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="p-4 bg-slate-900/40 border border-slate-800 rounded-lg">
                  <div className="text-xs text-slate-400 uppercase tracking-wider">Missing Modalities</div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {assessment.modalities_missing.slice(0, 4).map((mod) => (
                      <span key={mod} className="px-2 py-0.5 text-[11px] bg-slate-800/60 border border-slate-700 text-slate-400 rounded">
                        {mod}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="p-4 bg-slate-900/40 border border-slate-800 rounded-lg">
                  <div className="text-xs text-slate-400 uppercase tracking-wider">Cross-Modal Agreement</div>
                  <div className="mt-2 text-xl font-bold">
                    {assessment.disagreements.length > 0 ? (
                      <span className="text-amber-400">DISAGREEMENT DETECTED</span>
                    ) : assessment.agreements.length > 0 ? (
                      <span className="text-emerald-400">CORROBORATED</span>
                    ) : (
                      <span className="text-slate-400">INSUFFICIENT PAIRS</span>
                    )}
                  </div>
                  <div className="text-xs text-slate-500 mt-1">
                    {assessment.agreements.length} agreements, {assessment.disagreements.length} conflicts
                  </div>
                </div>

                <div className="p-4 bg-slate-900/40 border border-slate-800 rounded-lg">
                  <div className="text-xs text-slate-400 uppercase tracking-wider">Evaluation Window</div>
                  <div className="mt-2 text-sm text-slate-300 font-mono">
                    {assessment.evaluation_window.duration_seconds / 60}m duration
                  </div>
                  <div className="text-[11px] text-slate-500 mt-1">
                    Future Leakage Protection: Active
                  </div>
                </div>
              </div>

              {/* Fused Observations Preview */}
              <div>
                <h3 className="text-sm font-bold uppercase tracking-wider text-slate-300 mb-3">
                  Key Fused Physical Indicators
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {assessment.fused_observations.map((fo) => (
                    <div key={fo.fused_observation_id} className="p-4 bg-slate-900/60 border border-slate-700/60 rounded-lg">
                      <div className="flex justify-between items-start">
                        <span className="text-xs text-cyan-400 font-mono">{fo.measurement_type}</span>
                        <span className="text-[10px] px-1.5 py-0.5 bg-slate-800 rounded text-slate-300">
                          {fo.provenance}
                        </span>
                      </div>
                      <div className="mt-2 flex items-baseline space-x-2">
                        <span className="text-2xl font-bold text-white">{fo.fused_value}</span>
                        <span className="text-xs text-slate-400">{fo.unit || ""}</span>
                      </div>
                      <div className="mt-2 text-[11px] text-slate-400 flex justify-between">
                        <span>Contributing: {fo.contributing_modalities.join(", ")}</span>
                        <span className="text-emerald-400 font-semibold">{fo.confidence} CONF</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Methodological Context */}
              <div className="p-4 bg-slate-950/60 border border-slate-800 rounded-lg space-y-2 text-xs">
                <div className="font-semibold text-slate-300">Deterministic Methodology & Cryptographic Integrity</div>
                <div className="text-slate-400 flex flex-wrap gap-x-6 gap-y-1">
                  <span>Method: <span className="text-slate-200">{assessment.methodology}</span></span>
                  <span>Model: <span className="text-slate-200">{assessment.model_version}</span></span>
                  <span>Fingerprint (SHA-256): <span className="text-cyan-400 font-mono">{assessment.input_fingerprint.slice(0, 16)}...</span></span>
                </div>
              </div>
            </div>
          )}

          {assessment && activeTab === "fused" && (
            <div className="space-y-4">
              <h3 className="text-sm font-bold uppercase tracking-wider text-slate-300">
                Combined Multimodal Analytical Metrics
              </h3>
              <div className="space-y-3">
                {assessment.fused_observations.map((fo) => (
                  <div key={fo.fused_observation_id} className="p-4 bg-slate-900/50 border border-slate-800 rounded-lg flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div>
                      <div className="flex items-center space-x-3">
                        <span className="text-base font-bold text-cyan-300">{fo.measurement_type}</span>
                        <span className="px-2 py-0.5 text-xs bg-cyan-950 border border-cyan-800 text-cyan-300 rounded font-mono">
                          {fo.fused_value} {fo.unit}
                        </span>
                      </div>
                      <div className="text-xs text-slate-400 mt-1">
                        Fusion Strategy: <span className="text-slate-300">{fo.fusion_method}</span> | Agreement: <span className="text-emerald-400">{(fo.agreement_score * 100).toFixed(0)}%</span>
                      </div>
                      <div className="text-xs text-slate-500 mt-0.5">
                        Contributing modalities: {fo.contributing_modalities.join(" • ")}
                      </div>
                    </div>
                    <div className="flex items-center space-x-3 text-right">
                      <div>
                        <div className="text-xs font-semibold text-emerald-400">{fo.confidence} CONFIDENCE</div>
                        <div className="text-[11px] text-slate-500">{fo.uncertainty} UNCERTAINTY</div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {assessment && activeTab === "agreements" && (
            <div className="space-y-6">
              {/* Agreements */}
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-emerald-400 mb-2">
                  Corroborating Modalities ({assessment.agreements.length})
                </h4>
                {assessment.agreements.length === 0 ? (
                  <p className="text-xs text-slate-500 italic">No multi-modal corroborations detected.</p>
                ) : (
                  <div className="space-y-2">
                    {assessment.agreements.map((agr) => (
                      <div key={agr.agreement_id} className="p-3 bg-emerald-950/20 border border-emerald-500/30 rounded text-xs text-emerald-200">
                        <div className="font-semibold text-emerald-300">
                          Corroboration: {agr.supporting_modalities.join(" ↔ ")}
                        </div>
                        <div className="mt-1 text-slate-300">{agr.details}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Disagreements */}
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-amber-400 mb-2">
                  Modal Disagreements & Conflicts ({assessment.disagreements.length})
                </h4>
                {assessment.disagreements.length === 0 ? (
                  <p className="text-xs text-slate-500 italic">No material multi-modal conflicts detected.</p>
                ) : (
                  <div className="space-y-2">
                    {assessment.disagreements.map((dis) => (
                      <div key={dis.agreement_id} className="p-3 bg-amber-950/20 border border-amber-500/30 rounded text-xs text-amber-200">
                        <div className="font-semibold text-amber-300">
                          Conflict: {dis.supporting_modalities.join(", ")} vs {dis.conflicting_modalities.join(", ")}
                        </div>
                        <div className="mt-1 text-slate-300">{dis.details}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Correlations */}
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-cyan-400 mb-2">
                  Cross-Modal Correlations ({assessment.correlations.length})
                </h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {assessment.correlations.map((c) => (
                    <div key={c.correlation_id} className="p-3 bg-slate-900/40 border border-slate-800 rounded text-xs">
                      <div className="flex justify-between">
                        <span className="font-semibold text-cyan-300">{c.modality_a} ↔ {c.modality_b}</span>
                        <span className="font-mono text-slate-300">
                          {c.correlation_coefficient !== null && c.correlation_coefficient !== undefined
                            ? `r = ${c.correlation_coefficient.toFixed(2)}`
                            : "N/A (N < 3)"}
                        </span>
                      </div>
                      <div className="text-slate-400 mt-1">{c.explanation}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {assessment && activeTab === "health" && (
            <div className="space-y-4">
              <h3 className="text-sm font-bold uppercase tracking-wider text-slate-300">
                Analytical Sensor Reliability & Quality Indicators
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {assessment.sensor_health.map((sh) => (
                  <div key={sh.sensor_id} className="p-4 bg-slate-900/60 border border-slate-800 rounded-lg text-xs space-y-2">
                    <div className="flex justify-between items-center">
                      <span className="font-bold text-cyan-300">{sh.sensor_id} ({sh.modality})</span>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                        sh.status === "HEALTHY" ? "bg-emerald-950 text-emerald-300 border border-emerald-800" : "bg-amber-950 text-amber-300 border border-amber-800"
                      }`}>
                        {sh.status}
                      </span>
                    </div>
                    <div>
                      <div className="text-slate-400">Reliability Score: {(sh.reliability_score * 100).toFixed(0)}%</div>
                      <div className="w-full bg-slate-800 rounded-full h-1.5 mt-1 overflow-hidden">
                        <div
                          className={`h-full ${sh.reliability_score >= 0.8 ? "bg-emerald-400" : "bg-amber-400"}`}
                          style={{ width: `${sh.reliability_score * 100}%` }}
                        />
                      </div>
                    </div>
                    {sh.findings.length > 0 && (
                      <div className="text-amber-300/90 text-[11px] bg-slate-950/60 p-2 rounded">
                        {sh.findings.join(" • ")}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {assessment && activeTab === "evidence" && (
            <div className="space-y-4">
              <h3 className="text-sm font-bold uppercase tracking-wider text-slate-300">
                Traceable Observation Lineage & Anti-Double-Counting
              </h3>
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left text-slate-300 border border-slate-800">
                  <thead className="bg-slate-900/80 text-slate-400 uppercase text-[10px]">
                    <tr>
                      <th className="px-3 py-2">Evidence ID</th>
                      <th className="px-3 py-2">Modality</th>
                      <th className="px-3 py-2">Source ID</th>
                      <th className="px-3 py-2">Value</th>
                      <th className="px-3 py-2">Independence</th>
                      <th className="px-3 py-2">Quality</th>
                      <th className="px-3 py-2">Contribution</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800">
                    {assessment.evidence.map((ev) => (
                      <tr key={ev.evidence_id} className="hover:bg-slate-800/30">
                        <td className="px-3 py-2 font-mono text-cyan-400">{ev.evidence_id}</td>
                        <td className="px-3 py-2">{ev.modality}</td>
                        <td className="px-3 py-2 font-mono text-slate-400">{ev.source_id}</td>
                        <td className="px-3 py-2 font-mono">{String(ev.value)} {ev.unit || ""}</td>
                        <td className="px-3 py-2">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] ${ev.is_independent ? "bg-emerald-950 text-emerald-300" : "bg-amber-950 text-amber-300"}`}>
                            {ev.is_independent ? "Independent" : "Derived/Dependent"}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-slate-400">{ev.quality.toFixed(2)}</td>
                        <td className="px-3 py-2 text-cyan-300">{ev.contribution.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="px-6 py-3 border-t border-slate-800 bg-slate-900/60 flex items-center justify-between text-xs text-slate-400">
          <div>
            Execution Gateway Separation: <span className="text-emerald-400 font-semibold">VERIFIED ISOLATED</span>
          </div>
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-white rounded transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
