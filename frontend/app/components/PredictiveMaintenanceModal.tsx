"use client";

import React, { useState, useEffect, useCallback } from "react";
import { 
  X, RefreshCw, AlertTriangle, ShieldAlert,
  Activity, ArrowRight, Target, Wrench, 
  Clock, CheckCircle, ShieldCheck
} from "lucide-react";
import { analyzePredictiveMaintenance, getPredictiveMaintenanceAssessment } from "../../lib/api";

export function PredictiveMaintenanceModal({ 
  onClose,
  initialAssetId = ""
}: { 
  onClose: () => void;
  initialAssetId?: string;
}) {
  const [assetId, setAssetId] = useState(initialAssetId);
  const [loading, setLoading] = useState(false);
  const [assessment, setAssessment] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const runAnalysis = useCallback(async (targetId: string) => {
    if (!targetId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await analyzePredictiveMaintenance(targetId.trim(), "P7D");
      setAssessment(res);
    } catch (err: any) {
      setError(err.message || "Failed to run Predictive Maintenance Analysis.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (initialAssetId) {
      runAnalysis(initialAssetId);
    }
  }, [initialAssetId, runAnalysis]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    runAnalysis(assetId);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl w-full max-w-6xl max-h-[90vh] overflow-hidden flex flex-col text-slate-100 animate-in fade-in zoom-in-95 duration-200">
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/80">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-indigo-500/10 border border-indigo-500/20 rounded-lg text-indigo-400">
              <Wrench className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                Predictive Maintenance Intelligence
                <span className="text-xs font-mono uppercase bg-slate-800 text-indigo-400 px-2 py-0.5 rounded border border-indigo-500/20">
                  Read-Only Analytical View
                </span>
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Estimates maintenance-related risk using deterministic anomaly, quality, and twin signals.
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

        {/* Action Bar */}
        <div className="p-4 border-b border-slate-800 bg-slate-900 flex gap-4 items-end">
          <form onSubmit={handleSubmit} className="flex-1 flex gap-3 items-end max-w-2xl">
            <div className="flex-1">
              <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
                Target Asset ID
              </label>
              <input
                type="text"
                required
                value={assetId}
                onChange={(e) => setAssetId(e.target.value)}
                placeholder="e.g. pump_01, valve_12"
                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
              />
            </div>
            <button
              type="submit"
              disabled={loading || !assetId.trim()}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-sm rounded-lg transition-all shadow shadow-indigo-900/50 flex items-center gap-2 disabled:opacity-50"
            >
              {loading ? (
                <><RefreshCw className="w-4 h-4 animate-spin" /> Analyzing...</>
              ) : (
                <><Activity className="w-4 h-4" /> Run Assessment</>
              )}
            </button>
          </form>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto bg-slate-950/40 p-6">
          {error && (
            <div className="mb-6 p-4 bg-red-950/50 border border-red-800 rounded-xl flex items-start gap-3 text-red-400">
              <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
              <div>
                <h4 className="font-semibold text-sm">Analysis Failed</h4>
                <p className="text-xs opacity-90">{error}</p>
              </div>
            </div>
          )}

          {!assessment && !loading && !error && (
            <div className="h-64 flex flex-col items-center justify-center text-slate-500 text-sm">
              <Wrench className="w-12 h-12 mb-3 opacity-20" />
              <p>Enter a target asset ID to generate a predictive maintenance assessment.</p>
            </div>
          )}

          {assessment && (
            <div className="space-y-6">
              
              {/* Context & Scope Summary */}
              <div className="grid grid-cols-4 gap-4">
                <div className="col-span-4 lg:col-span-1 bg-slate-900 p-4 rounded-xl border border-slate-800 shadow-sm space-y-4">
                  <div>
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3">Assessment Context</h3>
                    <div className="space-y-2 text-xs font-mono">
                      <div className="flex justify-between text-slate-300">
                        <span>Assessment ID</span>
                        <span className="truncate max-w-[120px]" title={assessment.assessment_id}>{assessment.assessment_id}</span>
                      </div>
                      <div className="flex justify-between text-slate-300">
                        <span>Asset Type</span>
                        <span className="truncate max-w-[120px]">{assessment.asset_type}</span>
                      </div>
                      <div className="flex justify-between text-slate-300">
                        <span>Confidence</span>
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                          assessment.confidence === 'HIGH' ? 'bg-emerald-900/60 text-emerald-300' : 'bg-amber-900/60 text-amber-300'
                        }`}>{assessment.confidence}</span>
                      </div>
                      <div className="flex justify-between text-slate-300">
                        <span>Uncertainty</span>
                        <span className="truncate max-w-[120px]" title={assessment.uncertainty}>{assessment.uncertainty}</span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Score Metrics */}
                <div className="col-span-4 lg:col-span-3 bg-slate-900 p-4 rounded-xl border border-slate-800 shadow-sm">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-2">
                    <Activity className="w-4 h-4 text-emerald-400" />
                    Asset Intelligence Profile
                  </h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/60">
                      <span className="block text-[10px] text-slate-500 uppercase font-bold">Health Score</span>
                      <span className="text-lg font-bold text-white">{assessment.health_score.toFixed(1)}</span>
                    </div>
                    <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/60">
                      <span className="block text-[10px] text-slate-500 uppercase font-bold">Risk Level</span>
                      <span className={`text-lg font-bold ${
                        assessment.risk_level === 'CRITICAL' ? 'text-rose-500' :
                        assessment.risk_level === 'HIGH' ? 'text-orange-500' :
                        assessment.risk_level === 'MODERATE' ? 'text-amber-500' : 'text-emerald-500'
                      }`}>{assessment.risk_level}</span>
                    </div>
                    <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/60">
                      <span className="block text-[10px] text-slate-500 uppercase font-bold">Degradation</span>
                      <span className="text-lg font-bold text-rose-400">
                        {assessment.degradation_score.toFixed(1)}
                      </span>
                    </div>
                    <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/60">
                      <span className="block text-[10px] text-slate-500 uppercase font-bold">Horizon</span>
                      <span className="text-lg font-bold text-indigo-400">
                        {assessment.prediction_horizon}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Evidence */}
              <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-800 bg-slate-850">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Contributing Evidence</h3>
                </div>
                
                <div className="p-4 space-y-3">
                  {assessment.evidence && assessment.evidence.map((ev: any, idx: number) => (
                    <div key={`${ev.evidence_id}-${idx}`} className="p-3 bg-slate-950 rounded-xl border border-slate-800/80 shadow-sm">
                      <div className="flex justify-between items-start mb-2">
                        <span className="text-xs font-mono font-bold text-white">{ev.factor_type}</span>
                        <span className="text-[10px] font-bold text-slate-400 px-1.5 py-0.5 bg-slate-800 rounded">{ev.provenance}</span>
                      </div>
                      
                      <div className="flex items-center justify-between text-[10px] text-slate-400 mb-2">
                        <span>Source: {ev.source}</span>
                        <span>Weight: +{ev.contribution.toFixed(1)}</span>
                      </div>
                      
                      <p className="text-xs text-slate-300 bg-slate-900/50 p-2 rounded">
                        {ev.explanation}
                      </p>
                    </div>
                  ))}
                  
                  {(!assessment.evidence || assessment.evidence.length === 0) && (
                    <p className="text-xs text-center text-slate-500 py-4">No specific degradation evidence found.</p>
                  )}
                </div>
              </div>
              
              {/* Recommendations */}
              <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-800 bg-slate-850">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Analytical Recommendations</h3>
                </div>
                <div className="p-4 space-y-2">
                  <div className="mb-2 p-2 bg-indigo-950/30 border border-indigo-900/50 rounded-lg flex items-start gap-2 text-indigo-300">
                    <ShieldCheck className="w-4 h-4 shrink-0 mt-0.5" />
                    <p className="text-xs">
                      These recommendations are strictly analytical and evidence-backed. 
                      This subsystem does not possess execution authority.
                    </p>
                  </div>
                  {assessment.recommendations && assessment.recommendations.map((rec: any, i: number) => (
                    <div key={i} className="p-3 bg-slate-950 rounded-lg border border-slate-800">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-[10px] font-mono text-indigo-400 font-bold px-1.5 py-0.5 bg-indigo-950 rounded uppercase">{rec.action_type}</span>
                        <span className="text-xs text-white">{rec.description}</span>
                      </div>
                    </div>
                  ))}
                  {(!assessment.recommendations || assessment.recommendations.length === 0) && (
                    <p className="text-xs text-center text-slate-500 py-2">Asset is operating within normal parameters. No recommendations generated.</p>
                  )}
                </div>
              </div>

            </div>
          )}
        </div>

      </div>
    </div>
  );
}
