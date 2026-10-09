export async function fetchSage(endpoint: string, options: RequestInit = {}) {
  const token = (typeof window !== "undefined" && localStorage.getItem("sage_token")) || "manager_token";
  const defaultHeaders: Record<string, string> = {
    "Authorization": `Bearer ${token}`,
  };
  if (options.body && typeof options.body === "string") {
    defaultHeaders["Content-Type"] = "application/json";
  }

  const res = await fetch(`http://localhost:8000${endpoint}`, {
    ...options,
    headers: {
      ...defaultHeaders,
      ...((options.headers as Record<string, string>) || {}),
    },
  });

  if (!res.ok) {
    let errorMsg = `API error: ${res.status}`;
    try {
      const errorJson = await res.json();
      if (errorJson?.detail) {
        if (typeof errorJson.detail === "string") {
          errorMsg = errorJson.detail;
        } else if (errorJson.detail.message) {
          errorMsg = errorJson.detail.message;
        } else {
          errorMsg = JSON.stringify(errorJson.detail);
        }
      }
    } catch {
      // ignore json parse error
    }
    throw new Error(errorMsg);
  }
  return res.json();
}

// --- BLAST RADIUS API ---
export async function analyzeBlastRadius(sourceEntityId: string) {
  return fetchSage("/v3/blast-radius/analyze", {
    method: "POST",
    body: JSON.stringify({ source_entity_id: sourceEntityId }),
  });
}

export async function getBlastRadiusAnalysis(analysisId: string) {
  return fetchSage(`/v3/blast-radius/${analysisId}`);
}

// --- PREDICTIVE MAINTENANCE API ---
export async function analyzePredictiveMaintenance(assetId: string, horizon: string = "P7D") {
  return fetchSage("/v3/predictive-maintenance/analyze", {
    method: "POST",
    body: JSON.stringify({ asset_id: assetId, prediction_horizon: horizon }),
  });
}

export async function getPredictiveMaintenanceAssessment(assessmentId: string) {
  return fetchSage(`/v3/predictive-maintenance/assessment/${assessmentId}`);
}

// --- SLA / CUSTOMER RISK API ---
export async function analyzeSLACustomerRisk(payload: any) {
  return fetchSage("/api/v3/sla-customer-risk/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getSLACustomerRiskSummary(customerId: string) {
  return fetchSage(`/api/v3/sla-customer-risk/customer/${customerId}/summary`);
}

// --- FINANCIAL IMPACT API ---
export async function analyzeFinancialImpact(payload: any) {
  return fetchSage("/api/v3/financial-impact/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getFinancialImpactAssessment(assessmentId: string) {
  return fetchSage(`/api/v3/financial-impact/${assessmentId}`);
}

export async function listFinancialImpactSummary(limit: number = 50) {
  return fetchSage(`/api/v3/financial-impact/summary?limit=${limit}`);
}

// --- SUSTAINABILITY INTELLIGENCE API (Prompt 26 — ANALYTICAL ONLY) ---

export async function analyzeSustainability(payload: any) {
  return fetchSage("/api/v3/sustainability/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function runSustainabilityScenario(payload: any) {
  return fetchSage("/api/v3/sustainability/scenario", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getSustainabilityAssessment(assessmentId: string) {
  return fetchSage(`/api/v3/sustainability/${assessmentId}`);
}

export async function listSustainabilityAssessments(
  limit: number = 50,
  plantId?: string,
  assetId?: string
) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (plantId) params.append("plant_id", plantId);
  if (assetId) params.append("asset_id", assetId);
  return fetchSage(`/api/v3/sustainability?${params.toString()}`);
}

export async function listSustainabilitySummary(limit: number = 50) {
  return fetchSage(`/api/v3/sustainability/summary?limit=${limit}`);
}

// --- MULTIMODAL SENSOR FUSION API (Prompt 27 — ANALYTICAL ONLY) ---

export async function analyzeSensorFusion(payload: any) {
  return fetchSage("/api/v3/sensor-fusion/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getSensorFusionAssessment(assessmentId: string) {
  return fetchSage(`/api/v3/sensor-fusion/assessment/${assessmentId}`);
}

export async function listSensorFusionAssessments(
  limit: number = 50,
  targetEntityId?: string,
  plantId?: string
) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (targetEntityId) params.append("target_entity_id", targetEntityId);
  if (plantId) params.append("plant_id", plantId);
  return fetchSage(`/api/v3/sensor-fusion/assessments?${params.toString()}`);
}

export async function getSensorEntitySummary(entityId: string) {
  return fetchSage(`/api/v3/sensor-fusion/entities/${entityId}/summary`);
}

// --- WHAT-IF SIMULATION INTELLIGENCE API (Prompt 28 — ANALYTICAL ONLY) ---

export async function analyzeWhatIfSimulation(payload: any) {
  return fetchSage("/api/v3/what-if-simulation/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getWhatIfSimulation(simulationId: string) {
  return fetchSage(`/api/v3/what-if-simulation/${simulationId}`);
}

export async function listWhatIfSimulations(
  limit: number = 50,
  workspaceId?: string,
  plantId?: string
) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (workspaceId) params.append("workspace_id", workspaceId);
  if (plantId) params.append("plant_id", plantId);
  return fetchSage(`/api/v3/what-if-simulation?${params.toString()}`);
}

export async function getWhatIfSimulationImpact(simulationId: string) {
  return fetchSage(`/api/v3/what-if-simulation/${simulationId}/impact`);
}

export async function getWhatIfSimulationEvidence(simulationId: string) {
  return fetchSage(`/api/v3/what-if-simulation/${simulationId}/evidence`);
}

// --- OPTIMIZATION INTELLIGENCE API (Prompt 29 — ANALYTICAL DECISION SUPPORT ONLY) ---

export async function analyzeOptimization(payload: any) {
  return fetchSage("/api/v3/optimization/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getOptimization(optimizationId: string) {
  return fetchSage(`/api/v3/optimization/${optimizationId}`);
}

export async function listOptimizations(
  limit: number = 50,
  workspaceId?: string,
  plantId?: string
) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (workspaceId) params.append("workspace_id", workspaceId);
  if (plantId) params.append("plant_id", plantId);
  return fetchSage(`/api/v3/optimization?${params.toString()}`);
}

export async function getOptimizationCandidates(optimizationId: string) {
  return fetchSage(`/api/v3/optimization/${optimizationId}/candidates`);
}

export async function getOptimizationSensitivity(optimizationId: string) {
  return fetchSage(`/api/v3/optimization/${optimizationId}/sensitivity`);
}

export async function getOptimizationEvidence(optimizationId: string) {
  return fetchSage(`/api/v3/optimization/${optimizationId}/evidence`);
}

// --- DECISION ENGINE FOUNDATION API (Prompt 30 — ANALYTICAL DECISION SUPPORT ONLY) ---

export async function evaluateDecision(payload: any) {
  return fetchSage("/api/v3/decision-engine/evaluate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getDecision(decisionId: string) {
  return fetchSage(`/api/v3/decision-engine/${decisionId}`);
}

export async function listDecisions(
  limit: number = 50,
  workspaceId?: string,
  plantId?: string,
  decisionType?: string
) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (workspaceId) params.append("workspace_id", workspaceId);
  if (plantId) params.append("plant_id", plantId);
  if (decisionType) params.append("decision_type", decisionType);
  return fetchSage(`/api/v3/decision-engine?${params.toString()}`);
}

export async function getDecisionAlternatives(decisionId: string) {
  return fetchSage(`/api/v3/decision-engine/${decisionId}/alternatives`);
}

export async function getDecisionEvidence(decisionId: string) {
  return fetchSage(`/api/v3/decision-engine/${decisionId}/evidence`);
}

export async function getDecisionAudit(decisionId: string) {
  return fetchSage(`/api/v3/decision-engine/${decisionId}/audit`);
}



