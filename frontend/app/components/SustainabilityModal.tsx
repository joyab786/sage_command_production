"use client";

/**
 * frontend/app/components/SustainabilityModal.tsx
 *
 * SageCommand V3 — Sustainability Intelligence Modal (Prompt 26)
 *
 * ANALYTICAL ONLY — This component displays sustainability impact assessments.
 * It does NOT contain control commands, sustainability remediation buttons,
 * energy-control buttons, shutdown controls, procurement controls, financial
 * transaction controls, customer communication, or execution actions.
 *
 * Sustainability Intelligence is an analytical system. It does not directly
 * control physical systems, execute remediation, purchase offsets, submit
 * regulatory filings, or mutate operational/financial records.
 */

import React, { useState } from "react";
import * as api from "../../lib/api";

interface SustainabilityModalProps {
  isOpen: boolean;
  onClose: () => void;
  assetId?: string;
  supplierId?: string;
  customerId?: string;
  plantId?: string;
}

interface SustainabilityValue {
  amount: number | null;
  unit: string;
  value_type: string;
  provenance: string;
  confidence: string;
  source_reference?: string;
  gas_type?: string;
}

interface ImpactFactor {
  dimension: string;
  value: SustainabilityValue;
  confidence: string;
  provenance: string;
  explanation: string;
  data_quality_issues: string[];
  assumption_ids?: string[];
  factor_ids?: string[];
  intensity?: {
    result: number | null;
    result_unit: string | null;
    is_valid: boolean;
    invalidity_reason: string;
  };
}

interface RiskFactor {
  dimension: string;
  risk_level: string;
  score: number | null;
  rationale: string;
  confidence: string;
}

interface Assessment {
  assessment_id: string;
  assessment_timestamp: string;
  scenario: { scenario_name: string };
  confidence: string;
  confidence_rationale: string;
  factors: ImpactFactor[];
  risk_factors: RiskFactor[];
  data_quality_issues: string[];
  known_limitations: string[];
  analytical_disclaimer: string;
}

type ActiveTab = "overview" | "energy" | "emissions" | "water_waste" | "evidence" | "scenario";

// ── Styling helpers ────────────────────────────────────────────────────────

const CONFIDENCE_COLOR: Record<string, string> = {
  HIGH: "#22c55e",
  MEDIUM: "#eab308",
  LOW: "#f97316",
  INSUFFICIENT_DATA: "#64748b",
};

const RISK_COLOR: Record<string, string> = {
  CRITICAL: "#dc2626",
  HIGH: "#f97316",
  MEDIUM: "#eab308",
  LOW: "#22c55e",
  MINIMAL: "#10b981",
  UNKNOWN: "#64748b",
};

const DIMENSION_ICON: Record<string, string> = {
  ENERGY: "⚡",
  EMISSIONS: "🌫️",
  WATER: "💧",
  WASTE: "♻️",
  MATERIAL: "📦",
  RESOURCE: "🔩",
  SUSTAINABILITY_RISK: "⚠️",
};

function fmtValue(v: SustainabilityValue): string {
  if (v.amount === null || v.amount === undefined) return "UNKNOWN";
  return `${v.amount.toLocaleString("en-US", { maximumFractionDigits: 4 })} ${v.unit}`;
}

function fmtDimension(dim: string): string {
  return dim.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

function fmtProvenance(p: string): string {
  const labels: Record<string, string> = {
    OBSERVED: "Observed",
    DERIVED: "Derived",
    ESTIMATED: "Estimated",
    SIMULATED: "Simulated",
    UNKNOWN: "Unknown",
  };
  return labels[p] || p;
}

// ── Component ──────────────────────────────────────────────────────────────

export default function SustainabilityModal({
  isOpen,
  onClose,
  assetId,
  supplierId,
  customerId,
  plantId,
}: SustainabilityModalProps) {
  const [loading, setLoading] = useState(false);
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>("overview");

  const runAnalysis = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.analyzeSustainability({
        tenant_id: "tenant_default",
        asset_id: assetId,
        supplier_id: supplierId,
        customer_id: customerId,
        plant_id: plantId,
        scenario_name: "EXPECTED",
        evidence_payloads: [],
        assumptions: [],
        emissions_factors: [],
      });
      setAssessment(data as Assessment);
      setActiveTab("overview");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  const knownFactors =
    assessment?.factors.filter((f) => f.value.amount !== null && f.value.amount !== undefined) ?? [];
  const energyFactor = assessment?.factors.find((f) => f.dimension === "ENERGY");
  const emissionsFactor = assessment?.factors.find((f) => f.dimension === "EMISSIONS");
  const waterFactor = assessment?.factors.find((f) => f.dimension === "WATER");
  const wasteFactor = assessment?.factors.find((f) => f.dimension === "WASTE");
  const materialFactor = assessment?.factors.find((f) => f.dimension === "MATERIAL");

  const tabs: { id: ActiveTab; label: string; icon: string }[] = [
    { id: "overview", label: "Overview", icon: "🌱" },
    { id: "energy", label: "Energy", icon: "⚡" },
    { id: "emissions", label: "Emissions", icon: "🌫️" },
    { id: "water_waste", label: "Water / Waste", icon: "💧" },
    { id: "evidence", label: "Evidence & Quality", icon: "📋" },
    { id: "scenario", label: "Scenario", icon: "🔮" },
  ];

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.75)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
        backdropFilter: "blur(4px)",
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "linear-gradient(135deg, #0f172a 0%, #1e293b 100%)",
          border: "1px solid #22c55e33",
          borderRadius: 16,
          width: "min(900px, 95vw)",
          maxHeight: "90vh",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          boxShadow: "0 25px 60px rgba(0,0,0,0.7), 0 0 40px rgba(34,197,94,0.1)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Header ── */}
        <div
          style={{
            padding: "20px 24px",
            borderBottom: "1px solid #1e293b",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            background: "linear-gradient(90deg, rgba(34,197,94,0.08), transparent)",
          }}
        >
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
              <span style={{ fontSize: 22 }}>🌱</span>
              <h2
                style={{
                  margin: 0,
                  fontSize: 18,
                  fontWeight: 700,
                  color: "#f1f5f9",
                  letterSpacing: "-0.02em",
                }}
              >
                Sustainability Intelligence
              </h2>
              {/* ANALYTICAL ONLY badge — prominent, always visible */}
              <span
                style={{
                  background: "rgba(34,197,94,0.15)",
                  border: "1px solid rgba(34,197,94,0.4)",
                  color: "#22c55e",
                  fontSize: 10,
                  fontWeight: 700,
                  padding: "2px 8px",
                  borderRadius: 4,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                }}
              >
                ANALYTICAL ONLY
              </span>
            </div>
            <p style={{ margin: 0, fontSize: 12, color: "#64748b" }}>
              Deterministic sustainability impact analysis · No physical or financial actions
            </p>
          </div>
          <button
            id="sustainability-modal-close"
            onClick={onClose}
            style={{
              background: "none",
              border: "1px solid #334155",
              borderRadius: 8,
              color: "#94a3b8",
              cursor: "pointer",
              fontSize: 16,
              padding: "4px 10px",
            }}
          >
            ✕
          </button>
        </div>

        {/* ── ANALYTICAL ONLY disclaimer ── */}
        <div
          style={{
            margin: "0 24px",
            marginTop: 12,
            padding: "8px 12px",
            background: "rgba(34,197,94,0.06)",
            border: "1px solid rgba(34,197,94,0.15)",
            borderRadius: 8,
            fontSize: 11,
            color: "#94a3b8",
            lineHeight: 1.5,
          }}
        >
          <strong style={{ color: "#22c55e" }}>⚠ Analytical Only</strong> — This assessment does not
          represent carbon neutrality, net zero, ESG compliance, or regulatory compliance. All estimates
          are analytical only and must not be used as verified emissions reductions without independent
          validation. No physical systems are controlled, no offsets are purchased, no regulatory filings
          are submitted.
        </div>

        {/* ── Run Analysis Button ── */}
        {!assessment && (
          <div style={{ padding: "20px 24px" }}>
            <button
              id="sustainability-run-analysis"
              onClick={runAnalysis}
              disabled={loading}
              style={{
                background: loading
                  ? "rgba(34,197,94,0.2)"
                  : "linear-gradient(135deg, #16a34a, #22c55e)",
                border: "none",
                borderRadius: 10,
                color: "#fff",
                cursor: loading ? "wait" : "pointer",
                fontSize: 14,
                fontWeight: 600,
                padding: "12px 24px",
                width: "100%",
                letterSpacing: "0.02em",
                transition: "all 0.2s",
                boxShadow: loading ? "none" : "0 4px 12px rgba(34,197,94,0.3)",
              }}
            >
              {loading ? "⏳ Running Sustainability Analysis…" : "🌱 Run Sustainability Analysis"}
            </button>
            {error && (
              <div
                style={{
                  marginTop: 12,
                  padding: "10px 14px",
                  background: "rgba(239,68,68,0.1)",
                  border: "1px solid rgba(239,68,68,0.3)",
                  borderRadius: 8,
                  color: "#f87171",
                  fontSize: 13,
                }}
              >
                {error}
              </div>
            )}
          </div>
        )}

        {/* ── Tabs + Content ── */}
        {assessment && (
          <>
            {/* Tab Bar */}
            <div
              style={{
                display: "flex",
                gap: 2,
                padding: "12px 24px 0",
                borderBottom: "1px solid #1e293b",
                overflowX: "auto",
              }}
            >
              {tabs.map((t) => (
                <button
                  id={`sustainability-tab-${t.id}`}
                  key={t.id}
                  onClick={() => setActiveTab(t.id)}
                  style={{
                    background:
                      activeTab === t.id
                        ? "linear-gradient(135deg, rgba(34,197,94,0.2), rgba(34,197,94,0.08))"
                        : "transparent",
                    border:
                      activeTab === t.id ? "1px solid rgba(34,197,94,0.3)" : "1px solid transparent",
                    borderBottom: activeTab === t.id ? "1px solid #0f172a" : "none",
                    borderRadius: "8px 8px 0 0",
                    color: activeTab === t.id ? "#22c55e" : "#64748b",
                    cursor: "pointer",
                    fontSize: 12,
                    fontWeight: activeTab === t.id ? 600 : 400,
                    padding: "8px 14px",
                    whiteSpace: "nowrap",
                    transition: "all 0.15s",
                  }}
                >
                  {t.icon} {t.label}
                </button>
              ))}
              <button
                id="sustainability-re-run"
                onClick={() => { setAssessment(null); setError(null); }}
                style={{
                  marginLeft: "auto",
                  background: "transparent",
                  border: "1px solid #334155",
                  borderRadius: 8,
                  color: "#64748b",
                  cursor: "pointer",
                  fontSize: 11,
                  padding: "6px 12px",
                }}
              >
                ↺ Re-run
              </button>
            </div>

            {/* Tab Content */}
            <div
              style={{
                flex: 1,
                overflowY: "auto",
                padding: 24,
              }}
            >
              {/* OVERVIEW TAB */}
              {activeTab === "overview" && (
                <div style={{ display: "grid", gap: 16 }}>
                  {/* Header metrics */}
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
                    {/* Confidence */}
                    <div
                      style={{
                        background: "rgba(255,255,255,0.03)",
                        border: "1px solid #1e293b",
                        borderRadius: 10,
                        padding: "14px 16px",
                      }}
                    >
                      <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>
                        OVERALL CONFIDENCE
                      </div>
                      <div
                        style={{
                          fontSize: 20,
                          fontWeight: 700,
                          color: CONFIDENCE_COLOR[assessment.confidence] || "#94a3b8",
                        }}
                      >
                        {assessment.confidence.replace("_", " ")}
                      </div>
                    </div>

                    {/* Scenario */}
                    <div
                      style={{
                        background: "rgba(255,255,255,0.03)",
                        border: "1px solid #1e293b",
                        borderRadius: 10,
                        padding: "14px 16px",
                      }}
                    >
                      <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>SCENARIO</div>
                      <div style={{ fontSize: 16, fontWeight: 600, color: "#e2e8f0" }}>
                        {assessment.scenario.scenario_name}
                      </div>
                    </div>

                    {/* Known Dimensions */}
                    <div
                      style={{
                        background: "rgba(255,255,255,0.03)",
                        border: "1px solid #1e293b",
                        borderRadius: 10,
                        padding: "14px 16px",
                      }}
                    >
                      <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>
                        DIMENSIONS CALCULATED
                      </div>
                      <div style={{ fontSize: 20, fontWeight: 700, color: "#22c55e" }}>
                        {knownFactors.length}
                      </div>
                    </div>
                  </div>

                  {/* Confidence rationale */}
                  {assessment.confidence_rationale && (
                    <div
                      style={{
                        background: "rgba(255,255,255,0.02)",
                        border: "1px solid #1e293b",
                        borderRadius: 8,
                        padding: "10px 14px",
                        fontSize: 12,
                        color: "#94a3b8",
                      }}
                    >
                      <strong style={{ color: "#cbd5e1" }}>Confidence rationale:</strong>{" "}
                      {assessment.confidence_rationale}
                    </div>
                  )}

                  {/* All dimensions summary */}
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: "#94a3b8", marginBottom: 10 }}>
                      DIMENSION SUMMARY
                    </div>
                    <div style={{ display: "grid", gap: 8 }}>
                      {assessment.factors
                        .filter((f) => f.dimension !== "SUSTAINABILITY_RISK")
                        .map((f) => (
                          <div
                            key={f.dimension}
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: 12,
                              padding: "10px 14px",
                              background: "rgba(255,255,255,0.02)",
                              border: "1px solid #1e293b",
                              borderRadius: 8,
                            }}
                          >
                            <span style={{ fontSize: 18, minWidth: 24 }}>
                              {DIMENSION_ICON[f.dimension] || "📊"}
                            </span>
                            <div style={{ flex: 1 }}>
                              <div style={{ fontSize: 12, fontWeight: 600, color: "#e2e8f0" }}>
                                {fmtDimension(f.dimension)}
                              </div>
                              <div style={{ fontSize: 11, color: "#64748b" }}>
                                {fmtProvenance(f.provenance)} · {f.confidence.replace("_", " ")}
                              </div>
                            </div>
                            <div
                              style={{
                                fontSize: 13,
                                fontWeight: 600,
                                color:
                                  f.value.amount !== null
                                    ? CONFIDENCE_COLOR[f.confidence] || "#e2e8f0"
                                    : "#475569",
                                textAlign: "right",
                              }}
                            >
                              {fmtValue(f.value)}
                            </div>
                          </div>
                        ))}
                    </div>
                  </div>

                  {/* Risk factors */}
                  {assessment.risk_factors && assessment.risk_factors.length > 0 && (
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 600, color: "#94a3b8", marginBottom: 10 }}>
                        SUSTAINABILITY RISK (Analytical Classification · Not a Resource Quantity)
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                        {assessment.risk_factors.map((r) => (
                          <div
                            key={r.dimension}
                            style={{
                              padding: "8px 12px",
                              background: "rgba(255,255,255,0.02)",
                              border: `1px solid ${RISK_COLOR[r.risk_level] || "#1e293b"}33`,
                              borderRadius: 8,
                            }}
                          >
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                              <span style={{ fontSize: 11, color: "#94a3b8" }}>
                                {DIMENSION_ICON[r.dimension] || "📊"} {fmtDimension(r.dimension)}
                              </span>
                              <span
                                style={{
                                  fontSize: 11,
                                  fontWeight: 700,
                                  color: RISK_COLOR[r.risk_level] || "#64748b",
                                  padding: "2px 6px",
                                  borderRadius: 4,
                                  background: `${RISK_COLOR[r.risk_level] || "#64748b"}18`,
                                }}
                              >
                                {r.risk_level}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Timestamp */}
                  <div style={{ fontSize: 11, color: "#475569" }}>
                    Assessment timestamp: {assessment.assessment_timestamp}
                    {" · "}Assessment ID: {assessment.assessment_id}
                  </div>
                </div>
              )}

              {/* ENERGY TAB */}
              {activeTab === "energy" && (
                <FactorSection
                  factor={energyFactor}
                  title="Energy Consumption"
                  icon="⚡"
                  emptyMessage="No energy evidence provided. Energy values require explicit measured or derived energy evidence with a valid energy unit (kWh, MWh, etc.). Energy is not inferred from risk scores."
                />
              )}

              {/* EMISSIONS TAB */}
              {activeTab === "emissions" && (
                <div style={{ display: "grid", gap: 16 }}>
                  <FactorSection
                    factor={emissionsFactor}
                    title="Emissions (CO2e)"
                    icon="🌫️"
                    emptyMessage="No emissions evidence or validated emissions factor provided. Emissions require either: (1) direct CO2e evidence, (2) energy evidence + grid_emissions_factor, or (3) material evidence + material_emissions_factor."
                  />
                  <div
                    style={{
                      padding: "10px 14px",
                      background: "rgba(255,255,255,0.02)",
                      border: "1px solid #1e293b",
                      borderRadius: 8,
                      fontSize: 11,
                      color: "#64748b",
                    }}
                  >
                    <strong style={{ color: "#94a3b8" }}>Emissions methodology note:</strong> Emissions are
                    derived using explicit emissions factors only. CO2 and CO2e are never confused. A
                    financial risk score is never converted to emissions. Scope 1/2/3 classification
                    requires additional validated evidence beyond what is shown here.
                  </div>
                </div>
              )}

              {/* WATER / WASTE TAB */}
              {activeTab === "water_waste" && (
                <div style={{ display: "grid", gap: 20 }}>
                  <FactorSection
                    factor={waterFactor}
                    title="Water Consumption"
                    icon="💧"
                    emptyMessage="No water consumption evidence provided. Water values require explicit measured evidence with a valid water unit (liters, m3, etc.)."
                  />
                  <FactorSection
                    factor={wasteFactor}
                    title="Waste"
                    icon="♻️"
                    emptyMessage="No waste evidence provided. Waste values require explicit evidence with a valid waste unit (kg, tonnes, etc.). Hazardous/non-hazardous classification is not inferred without explicit evidence."
                  />
                  <FactorSection
                    factor={materialFactor}
                    title="Material Consumption"
                    icon="📦"
                    emptyMessage="No material consumption evidence provided."
                  />
                </div>
              )}

              {/* EVIDENCE & QUALITY TAB */}
              {activeTab === "evidence" && (
                <div style={{ display: "grid", gap: 16 }}>
                  {/* Assumptions */}
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: "#94a3b8", marginBottom: 8 }}>
                      ASSUMPTIONS
                    </div>
                    {assessment.factors.flatMap((f) => f.assumption_ids).length === 0 ? (
                      <EmptyState message="No validated assumptions were used in this assessment." />
                    ) : (
                      <div style={{ fontSize: 12, color: "#94a3b8" }}>
                        Assumption IDs referenced by factors are embedded in the calculation detail for each dimension.
                      </div>
                    )}
                  </div>

                  {/* Data Quality Issues */}
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: "#94a3b8", marginBottom: 8 }}>
                      DATA QUALITY ISSUES
                    </div>
                    {assessment.data_quality_issues.length === 0 ? (
                      <div style={{ fontSize: 12, color: "#22c55e" }}>✓ No data quality issues detected</div>
                    ) : (
                      <div style={{ display: "grid", gap: 4 }}>
                        {assessment.data_quality_issues.map((issue, i) => (
                          <div
                            key={i}
                            style={{
                              padding: "6px 10px",
                              background: "rgba(239,68,68,0.06)",
                              border: "1px solid rgba(239,68,68,0.2)",
                              borderRadius: 6,
                              fontSize: 11,
                              color: "#f87171",
                              fontFamily: "monospace",
                            }}
                          >
                            {issue}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Known Limitations */}
                  {assessment.known_limitations.length > 0 && (
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 600, color: "#94a3b8", marginBottom: 8 }}>
                        KNOWN LIMITATIONS
                      </div>
                      <div style={{ display: "grid", gap: 4 }}>
                        {assessment.known_limitations.map((lim, i) => (
                          <div
                            key={i}
                            style={{
                              padding: "6px 10px",
                              background: "rgba(234,179,8,0.06)",
                              border: "1px solid rgba(234,179,8,0.2)",
                              borderRadius: 6,
                              fontSize: 11,
                              color: "#fbbf24",
                            }}
                          >
                            {lim}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* SCENARIO TAB */}
              {activeTab === "scenario" && (
                <div style={{ display: "grid", gap: 16 }}>
                  <div
                    style={{
                      padding: "14px 16px",
                      background: "rgba(255,255,255,0.02)",
                      border: "1px solid #1e293b",
                      borderRadius: 10,
                    }}
                  >
                    <div style={{ fontSize: 12, fontWeight: 600, color: "#94a3b8", marginBottom: 8 }}>
                      CURRENT SCENARIO
                    </div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: "#e2e8f0", marginBottom: 4 }}>
                      {assessment.scenario.scenario_name}
                    </div>
                    <div style={{ fontSize: 12, color: "#64748b" }}>
                      Scenario-derived values are marked SIMULATED. Scenario analysis never mutates
                      operational records.
                    </div>
                  </div>

                  <div
                    style={{
                      padding: "10px 14px",
                      background: "rgba(99,102,241,0.06)",
                      border: "1px solid rgba(99,102,241,0.2)",
                      borderRadius: 8,
                      fontSize: 11,
                      color: "#94a3b8",
                    }}
                  >
                    To run a stress or custom scenario, provide scenario_name = &quot;STRESS&quot; or
                    &quot;CUSTOM&quot; in the analyze request with scenario-specific assumptions. Scenario
                    results will be marked with provenance = &quot;SIMULATED&quot;.
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────

function FactorSection({
  factor,
  title,
  icon,
  emptyMessage,
}: {
  factor: ImpactFactor | undefined;
  title: string;
  icon: string;
  emptyMessage: string;
}) {
  if (!factor || factor.value.amount === null || factor.value.amount === undefined) {
    return (
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: "#94a3b8", marginBottom: 10 }}>
          {icon} {title}
        </div>
        <EmptyState message={emptyMessage} />
      </div>
    );
  }

  const CONFIDENCE_COLOR: Record<string, string> = {
    HIGH: "#22c55e",
    MEDIUM: "#eab308",
    LOW: "#f97316",
    INSUFFICIENT_DATA: "#64748b",
  };

  return (
    <div>
      <div style={{ fontSize: 13, fontWeight: 600, color: "#94a3b8", marginBottom: 10 }}>
        {icon} {title}
      </div>
      <div style={{ display: "grid", gap: 10 }}>
        {/* Value */}
        <div
          style={{
            padding: "14px 16px",
            background: "rgba(255,255,255,0.03)",
            border: "1px solid #1e293b",
            borderRadius: 10,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <div style={{ fontSize: 11, color: "#64748b" }}>VALUE</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: "#f1f5f9" }}>
                {factor.value.amount?.toLocaleString("en-US", { maximumFractionDigits: 4 })}
                <span style={{ fontSize: 14, color: "#94a3b8", marginLeft: 4 }}>{factor.value.unit}</span>
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: 11, color: "#64748b" }}>CONFIDENCE</div>
              <div
                style={{
                  fontSize: 14,
                  fontWeight: 700,
                  color: CONFIDENCE_COLOR[factor.confidence] || "#94a3b8",
                }}
              >
                {factor.confidence.replace("_", " ")}
              </div>
            </div>
          </div>
          {factor.value.gas_type && (
            <div style={{ marginTop: 8, fontSize: 11, color: "#64748b" }}>
              Gas type: <strong style={{ color: "#94a3b8" }}>{factor.value.gas_type}</strong>
            </div>
          )}
        </div>

        {/* Provenance */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 8,
          }}
        >
          <InfoChip label="Provenance" value={factor.provenance} />
          <InfoChip
            label="Intensity"
            value={
              factor.intensity?.is_valid
                ? `${factor.intensity.result?.toFixed(6)} ${factor.intensity.result_unit}`
                : factor.intensity?.invalidity_reason || "Not calculated"
            }
          />
        </div>

        {/* Explanation */}
        {factor.explanation && (
          <div
            style={{
              padding: "8px 12px",
              background: "rgba(255,255,255,0.02)",
              border: "1px solid #1e293b",
              borderRadius: 8,
              fontSize: 11,
              color: "#94a3b8",
              lineHeight: 1.6,
            }}
          >
            {factor.explanation}
          </div>
        )}

        {/* Data quality issues */}
        {factor.data_quality_issues.length > 0 && (
          <div style={{ display: "grid", gap: 4 }}>
            {factor.data_quality_issues.map((issue, i) => (
              <div
                key={i}
                style={{
                  padding: "4px 8px",
                  background: "rgba(239,68,68,0.06)",
                  borderRadius: 4,
                  fontSize: 11,
                  color: "#f87171",
                  fontFamily: "monospace",
                }}
              >
                {issue}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function InfoChip({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        padding: "8px 12px",
        background: "rgba(255,255,255,0.02)",
        border: "1px solid #1e293b",
        borderRadius: 8,
      }}
    >
      <div style={{ fontSize: 10, color: "#475569", marginBottom: 2 }}>{label.toUpperCase()}</div>
      <div style={{ fontSize: 12, color: "#94a3b8" }}>{value}</div>
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div
      style={{
        padding: "14px 16px",
        background: "rgba(255,255,255,0.02)",
        border: "1px dashed #334155",
        borderRadius: 8,
        fontSize: 12,
        color: "#475569",
        lineHeight: 1.6,
      }}
    >
      {message}
    </div>
  );
}
