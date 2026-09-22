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
