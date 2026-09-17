"use client";

import React, { useState, useCallback } from "react";
import { format } from "date-fns";
import { X, Search, ShieldAlert, Cpu, Layers, Activity } from "lucide-react";
import { fetchSage } from "../../lib/api";

export function RCAModal({ onClose, incidentId = "" }: { onClose: () => void; incidentId?: string }) {
  const [targetIncident, setTargetIncident] = useState(incidentId);
  const [evidenceIds, setEvidenceIds] = useState("");
  
  const [loading, setLoading] = useState(false);
  const [analysis, setAnalysis] = useState<any>(null);
  const [errorMsg, setErrorMsg] = useState("");

  const handleAnalyze = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetIncident.trim()) return;

    setLoading(true);
    setErrorMsg("");
    setAnalysis(null);

    try {
      const eList = evidenceIds.split(",").map(s => s.trim()).filter(Boolean);
      const res = await fetchSage(`/api/v3/rca/analyze/${targetIncident}`, {
        method: "POST",
        body: JSON.stringify({
          evidence_ids: eList,
          kg_version: "latest",
          twin_snapshot_id: "current"
        })
      });
      setAnalysis(res);
    } catch (err: any) {
      setErrorMsg(err.message || "Failed to trigger RCA.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col text-slate-100 animate-in fade-in zoom-in-95 duration-200">
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/70">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-500/10 border border-purple-500/20 rounded-lg text-purple-400">
              <Cpu className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                Root-Cause Analysis (RCA)
                <span className="text-xs font-mono uppercase bg-slate-800 text-purple-400 px-2 py-0.5 rounded border border-purple-500/20">
                  Prompt 19 Foundation
                </span>
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Deterministic reasoning and candidate ranking. Strict read-only isolation.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-white bg-slate-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Security Banner */}
        <div className="px-6 py-1.5 bg-slate-950 border-b border-slate-800/80 flex items-center justify-between text-[11px] text-slate-400 font-mono">
          <div className="flex items-center gap-2">
            <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
            <span>Execution Boundary: Active</span>
          </div>
          <div className="text-amber-400/90 font-sans text-[11px]">
            RCA is purely observational. It cannot mutate incident states or trigger remediation.
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {errorMsg && (
            <div className="p-3 bg-red-950/50 border border-red-900 rounded-lg text-red-400 text-xs flex items-center gap-2">
              <ShieldAlert className="w-4 h-4" />
              {errorMsg}
            </div>
          )}

          {/* Trigger Form */}
          <form onSubmit={handleAnalyze} className="bg-slate-850 p-5 rounded-xl border border-slate-800 space-y-4 shadow-sm">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <Search className="w-4 h-4 text-purple-400" />
              Trigger Analysis
            </h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-slate-400 mb-1">Target Incident ID</label>
                <input
                  required
                  type="text"
                  value={targetIncident}
                  onChange={(e) => setTargetIncident(e.target.value)}
                  placeholder="e.g. inc_a1b2c3"
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-purple-500"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Evidence IDs (comma-separated)</label>
                <input
                  type="text"
                  value={evidenceIds}
                  onChange={(e) => setEvidenceIds(e.target.value)}
                  placeholder="e.g. evt_99x, anom_88y"
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-purple-500"
                />
              </div>
            </div>
            <div className="flex justify-end">
              <button
                type="submit"
                disabled={loading || !targetIncident}
                className="px-5 py-2 bg-purple-600 hover:bg-purple-500 text-white font-semibold text-xs rounded-lg transition-all disabled:opacity-50 flex items-center gap-2"
              >
                {loading ? (
                  <>
                    <Activity className="w-4 h-4 animate-spin" />
                    Analyzing...
                  </>
                ) : (
                  "Execute Deterministic RCA"
                )}
              </button>
            </div>
          </form>

          {/* Analysis Results */}
          {analysis && (
            <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
              
              <div className="flex justify-between items-end">
                <div>
                  <h3 className="text-lg font-bold text-white">Analysis Findings</h3>
                  <div className="text-xs text-slate-400 font-mono mt-1">
                    Analysis ID: <span className="text-purple-300">{analysis.analysis_id}</span> • Status: <span className="text-emerald-400">{analysis.status}</span>
                  </div>
                </div>
                <div className="text-[10px] text-slate-500 font-mono">
                  Completed At: {format(new Date(analysis.completed_at || analysis.started_at), "yyyy-MM-dd HH:mm:ss")}
                </div>
              </div>

              {analysis.causes?.length === 0 ? (
                <div className="p-8 text-center text-slate-500 text-sm bg-slate-850 rounded-xl border border-slate-800">
                  No cause candidates could be deterministically verified.
                </div>
              ) : (
                <div className="space-y-3">
                  {analysis.causes?.map((cause: any, idx: number) => (
                    <div key={cause.cause_id} className="bg-slate-850 p-4 rounded-xl border border-slate-700 shadow-sm flex flex-col gap-3">
                      <div className="flex justify-between items-start">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-mono uppercase bg-slate-800 text-slate-300 px-2 py-0.5 rounded border border-slate-700">
                              Rank {idx + 1}
                            </span>
                            <span className="text-sm font-bold text-white">{cause.label}</span>
                          </div>
                          <p className="text-xs text-slate-400">{cause.description}</p>
                        </div>
                        <div className="text-right">
                          <div className="text-2xl font-black text-purple-400">{cause.score.toFixed(1)}</div>
                          <div className="text-[9px] uppercase tracking-wider text-slate-500">Confidence Score</div>
                        </div>
                      </div>

                      <div className="grid grid-cols-3 gap-2 mt-2">
                        <div className="bg-slate-900/50 p-2 rounded text-[10px] font-mono border border-slate-800/50">
                          <span className="block text-slate-500 mb-0.5">Cause Type</span>
                          <span className="text-slate-300">{cause.cause_type}</span>
                        </div>
                        <div className="bg-slate-900/50 p-2 rounded text-[10px] font-mono border border-slate-800/50">
                          <span className="block text-slate-500 mb-0.5">Confidence Level</span>
                          <span className="text-slate-300">{cause.confidence}</span>
                        </div>
                        <div className="bg-slate-900/50 p-2 rounded text-[10px] font-mono border border-slate-800/50">
                          <span className="block text-slate-500 mb-0.5">Data Quality</span>
                          <span className="text-slate-300">{cause.data_quality_state}</span>
                        </div>
                      </div>
                      
                      {cause.temporal_support && (
                        <div className="mt-1 pt-2 border-t border-slate-800">
                          <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1 block">Temporal Trace</span>
                          <div className="text-[10px] font-mono text-slate-300">
                            {cause.temporal_support.temporal_relation} window of {cause.temporal_support.time_difference_ms}ms gap.
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
