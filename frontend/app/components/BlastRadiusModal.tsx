"use client";

import React, { useState, useEffect, useCallback } from "react";
import { 
  Network, X, RefreshCw, AlertTriangle, ShieldAlert,
  Activity, ArrowRight, Layers, Target, Database,
  TrendingDown, TrendingUp
} from "lucide-react";
import { analyzeBlastRadius } from "../../lib/api";

export function BlastRadiusModal({ 
  onClose,
  initialEntityId = ""
}: { 
  onClose: () => void;
  initialEntityId?: string;
}) {
  const [entityId, setEntityId] = useState(initialEntityId);
  const [loading, setLoading] = useState(false);
  const [analysis, setAnalysis] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const runAnalysis = useCallback(async (targetId: string) => {
    if (!targetId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await analyzeBlastRadius(targetId.trim());
      setAnalysis(res);
    } catch (err: any) {
      setError(err.message || "Failed to run Blast Radius Analysis.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (initialEntityId) {
      runAnalysis(initialEntityId);
    }
  }, [initialEntityId, runAnalysis]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    runAnalysis(entityId);
  };

  // Group nodes by distance
  const groupedNodes: Record<number, any[]> = {};
  if (analysis && analysis.nodes) {
    analysis.nodes.forEach((n: any) => {
      if (!groupedNodes[n.distance]) groupedNodes[n.distance] = [];
      groupedNodes[n.distance].push(n);
    });
  }

  const distances = Object.keys(groupedNodes).map(Number).sort((a, b) => a - b);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl w-full max-w-6xl max-h-[90vh] overflow-hidden flex flex-col text-slate-100 animate-in fade-in zoom-in-95 duration-200">
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/80">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-rose-500/10 border border-rose-500/20 rounded-lg text-rose-400">
              <Network className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                Blast-Radius Intelligence
                <span className="text-xs font-mono uppercase bg-slate-800 text-rose-400 px-2 py-0.5 rounded border border-rose-500/20">
                  Deterministic Propagation
                </span>
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Evaluates downstream and upstream cascading impact from an anomaly or incident using the Operational Knowledge Graph.
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
                Target Entity ID (Source)
              </label>
              <input
                type="text"
                required
                value={entityId}
                onChange={(e) => setEntityId(e.target.value)}
                placeholder="e.g. mix_motor_01, valve_12"
                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-rose-500"
              />
            </div>
            <button
              type="submit"
              disabled={loading || !entityId.trim()}
              className="px-4 py-2 bg-rose-600 hover:bg-rose-500 text-white font-semibold text-sm rounded-lg transition-all shadow shadow-rose-900/50 flex items-center gap-2 disabled:opacity-50"
            >
              {loading ? (
                <><RefreshCw className="w-4 h-4 animate-spin" /> Analyzing...</>
              ) : (
                <><Target className="w-4 h-4" /> Run Impact Analysis</>
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

          {!analysis && !loading && !error && (
            <div className="h-64 flex flex-col items-center justify-center text-slate-500 text-sm">
              <Network className="w-12 h-12 mb-3 opacity-20" />
              <p>Enter a target entity ID to generate a blast-radius propagation model.</p>
            </div>
          )}

          {analysis && (
            <div className="space-y-6">
              
              {/* Context & Scope Summary */}
              <div className="grid grid-cols-4 gap-4">
                <div className="col-span-4 lg:col-span-1 bg-slate-900 p-4 rounded-xl border border-slate-800 shadow-sm space-y-4">
                  <div>
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3">Analysis Context</h3>
                    <div className="space-y-2 text-xs font-mono">
                      <div className="flex justify-between text-slate-300">
                        <span>Analysis ID</span>
                        <span className="truncate max-w-[120px]" title={analysis.analysis_id}>{analysis.analysis_id}</span>
                      </div>
                      <div className="flex justify-between text-slate-300">
                        <span>Status</span>
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                          analysis.analysis_status === 'COMPLETED' ? 'bg-emerald-900/60 text-emerald-300' : 'bg-rose-900/60 text-rose-300'
                        }`}>{analysis.analysis_status}</span>
                      </div>
                      <div className="flex justify-between text-slate-300">
                        <span>Confidence</span>
                        <span>{analysis.confidence}</span>
                      </div>
                      <div className="flex justify-between text-slate-300">
                        <span>Snapshot</span>
                        <span className="truncate max-w-[120px]">{analysis.snapshot_timestamp}</span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Scope Metrics */}
                <div className="col-span-4 lg:col-span-3 bg-slate-900 p-4 rounded-xl border border-slate-800 shadow-sm">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-2">
                    <Layers className="w-4 h-4 text-amber-400" />
                    Impact Scope (Bounded Traversal)
                  </h3>
                  {analysis.scope ? (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/60">
                        <span className="block text-[10px] text-slate-500 uppercase font-bold">Assets Affected</span>
                        <span className="text-lg font-bold text-white">{analysis.scope.total_assets}</span>
                      </div>
                      <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/60">
                        <span className="block text-[10px] text-slate-500 uppercase font-bold">Processes</span>
                        <span className="text-lg font-bold text-white">{analysis.scope.total_processes}</span>
                      </div>
                      <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/60">
                        <span className="block text-[10px] text-slate-500 uppercase font-bold">Upstream Deps</span>
                        <span className="text-lg font-bold text-blue-400 flex items-center gap-1">
                          <TrendingDown className="w-3.5 h-3.5" />
                          {analysis.scope.total_upstream_dependencies}
                        </span>
                      </div>
                      <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/60">
                        <span className="block text-[10px] text-slate-500 uppercase font-bold">Downstream Deps</span>
                        <span className="text-lg font-bold text-orange-400 flex items-center gap-1">
                          <TrendingUp className="w-3.5 h-3.5" />
                          {analysis.scope.total_downstream_dependencies}
                        </span>
                      </div>
                    </div>
                  ) : (
                    <p className="text-xs text-slate-500">Scope data unavailable.</p>
                  )}
                </div>
              </div>

              {/* Propagation Chain (Nodes by Distance) */}
              <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-800 bg-slate-850">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Cascading Impact Nodes</h3>
                </div>
                
                <div className="p-4 space-y-6">
                  {distances.map(d => (
                    <div key={d} className="space-y-3">
                      <div className="flex items-center gap-2">
                        <div className="h-px bg-slate-800 flex-1"></div>
                        <span className="text-[10px] font-mono text-slate-500 uppercase font-bold px-2">
                          {d === 0 ? "Source Target (Depth 0)" : `Impact Depth ${d}`}
                        </span>
                        <div className="h-px bg-slate-800 flex-1"></div>
                      </div>
                      
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {groupedNodes[d].map((node: any, idx: number) => (
                          <div key={`${node.entity_id}-${idx}`} className={`p-3 rounded-xl border shadow-sm ${
                            d === 0 ? "bg-rose-950/20 border-rose-900/50" : "bg-slate-950 border-slate-800/80"
                          }`}>
                            <div className="flex justify-between items-start mb-2">
                              <span className="text-xs font-mono font-bold text-white">{node.entity_id}</span>
                              <span className="text-[10px] font-bold text-slate-400 px-1.5 py-0.5 bg-slate-800 rounded">{node.entity_type}</span>
                            </div>
                            
                            <div className="flex items-center justify-between text-[10px]">
                              <span className="text-slate-500 uppercase tracking-wider">Impact Class</span>
                              <span className={`font-bold ${
                                node.impact_classification === 'DIRECT' ? 'text-rose-400' :
                                node.impact_classification === 'DOWNSTREAM' ? 'text-orange-400' :
                                node.impact_classification === 'UPSTREAM' ? 'text-blue-400' : 'text-slate-400'
                              }`}>{node.impact_classification}</span>
                            </div>
                            
                            <div className="flex items-center justify-between text-[10px] mt-1.5 pt-1.5 border-t border-slate-800/60">
                              <span className="text-slate-500 uppercase tracking-wider">Score</span>
                              <div className="flex items-center gap-2 w-24">
                                <div className="h-1.5 flex-1 bg-slate-800 rounded-full overflow-hidden">
                                  <div 
                                    className={`h-full ${node.impact_score > 70 ? 'bg-rose-500' : node.impact_score > 40 ? 'bg-amber-500' : 'bg-blue-500'}`}
                                    style={{ width: `${node.impact_score}%` }}
                                  ></div>
                                </div>
                                <span className="font-mono text-slate-300 w-8 text-right">{node.impact_score.toFixed(0)}</span>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                  
                  {distances.length === 0 && (
                    <p className="text-xs text-center text-slate-500 py-4">No impact nodes discovered.</p>
                  )}
                </div>
              </div>
              
              {/* Propagation Paths */}
              <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-800 bg-slate-850">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Critical Paths</h3>
                </div>
                <div className="p-4 space-y-2">
                  {analysis.paths && analysis.paths.slice(0, 10).map((path: any, i: number) => (
                    <div key={i} className="p-2.5 bg-slate-950 rounded-lg border border-slate-800 text-xs font-mono flex items-center flex-wrap gap-2 text-slate-400">
                      {path.ordered_path.map((node: string, j: number) => (
                        <React.Fragment key={`${i}-${j}`}>
                          <span className={j === 0 ? "text-rose-400 font-bold" : "text-white"}>{node}</span>
                          {j < path.ordered_path.length - 1 && (
                            <div className="flex items-center text-slate-600 gap-1 px-1">
                              <span className="text-[9px] uppercase">{path.relationship_types[j]}</span>
                              <ArrowRight className="w-3 h-3" />
                            </div>
                          )}
                        </React.Fragment>
                      ))}
                    </div>
                  ))}
                  {analysis.paths && analysis.paths.length > 10 && (
                    <div className="text-center text-[10px] text-slate-500 pt-2">
                      Showing 10 of {analysis.paths.length} critical paths.
                    </div>
                  )}
                  {(!analysis.paths || analysis.paths.length === 0) && (
                    <p className="text-xs text-center text-slate-500 py-2">No propagation paths available.</p>
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
