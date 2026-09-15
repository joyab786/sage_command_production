"use client";

import React, { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  X,
  Network,
  Search,
  RefreshCw,
  Clock,
  ArrowRight,
  ShieldCheck,
  Activity,
  AlertTriangle,
  GitCommit,
  CheckCircle2,
  Database,
  Tag,
  Compass
} from "lucide-react";

interface OperationalFact {
  fact_id: string;
  subject_entity_id: string;
  predicate: string;
  object_entity_id?: string | null;
  value_type: string;
  value: any;
  unit?: string | null;
  source_type: string;
  source_id: string;
  observed_at: string;
  valid_from: string;
  valid_to?: string | null;
  status: string;
  confidence?: number | null;
}

interface GraphNeighbor {
  entity_id: string;
  entity_type: string;
  display_name: string;
  relationship_type: string;
  direction: string;
  edge_source: string;
  valid_from?: string | null;
  valid_to?: string | null;
  freshness?: string | null;
}

interface GraphNode {
  entity_id: string;
  entity_type: string;
  canonical_name: string;
  display_name: string;
  tenant_id: string;
  lifecycle_status: string;
  operational_status?: string | null;
  active_facts: OperationalFact[];
  freshness: string;
  last_observed_at?: string | null;
}

interface ValidationReport {
  is_valid: boolean;
  error_count: number;
  warning_count: number;
  timestamp: string;
  issues: Array<{
    severity: string;
    issue_type: string;
    entity_id?: string | null;
    message: string;
  }>;
}

interface KnowledgeGraphModalProps {
  isOpen: boolean;
  onClose: () => void;
  token?: string;
}

export default function KnowledgeGraphModal({ isOpen, onClose, token }: KnowledgeGraphModalProps) {
  const [activeTab, setActiveTab] = useState<"facts" | "neighbors" | "path" | "validation">("facts");
  const [entities, setEntities] = useState<Array<{ entity_id: string; display_name: string; entity_type: string }>>([]);
  const [selectedEntityId, setSelectedEntityId] = useState<string>("");
  const [nodeData, setNodeData] = useState<GraphNode | null>(null);
  const [neighbors, setNeighbors] = useState<GraphNeighbor[]>([]);
  const [targetEntityId, setTargetEntityId] = useState("");
  const [pathResult, setPathResult] = useState<any | null>(null);
  const [validationReport, setValidationReport] = useState<ValidationReport | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);

  const authToken = token || "dev_token";

  useEffect(() => {
    if (isOpen) {
      loadInitialEntities();
    }
  }, [isOpen]);

  useEffect(() => {
    if (selectedEntityId) {
      fetchNodeDetails(selectedEntityId);
    }
  }, [selectedEntityId]);

  const loadInitialEntities = async () => {
    try {
      setIsLoading(true);
      setError(null);
      const res = await fetch("/api/v3/ontology/entities?limit=50", {
        headers: { Authorization: `Bearer ${authToken}` }
      });
      if (res.ok) {
        const json = await res.json();
        const list = json.data || [];
        setEntities(list);
        if (list.length > 0 && !selectedEntityId) {
          setSelectedEntityId(list[0].entity_id);
        }
      }
    } catch (err: any) {
      setError(err.message || "Failed to load entities");
    } finally {
      setIsLoading(false);
    }
  };

  const fetchNodeDetails = async (id: string) => {
    try {
      setIsLoading(true);
      setError(null);
      // Fetch node data
      const resNode = await fetch(`/api/v3/knowledge-graph/entities/${encodeURIComponent(id)}`, {
        headers: { Authorization: `Bearer ${authToken}` }
      });
      if (resNode.ok) {
        const json = await resNode.json();
        setNodeData(json.data);
      }

      // Fetch neighbors
      const resNb = await fetch(`/api/v3/knowledge-graph/entities/${encodeURIComponent(id)}/neighbors?direction=BOTH`, {
        headers: { Authorization: `Bearer ${authToken}` }
      });
      if (resNb.ok) {
        const json = await resNb.json();
        setNeighbors(json.neighbors || []);
      }
    } catch (err: any) {
      setError(err.message || "Failed to fetch knowledge graph node");
    } finally {
      setIsLoading(false);
    }
  };

  const handleFindPath = async () => {
    if (!selectedEntityId || !targetEntityId) return;
    try {
      setIsLoading(true);
      setError(null);
      const res = await fetch(
        `/api/v3/knowledge-graph/path?source=${encodeURIComponent(selectedEntityId)}&target=${encodeURIComponent(targetEntityId)}&max_depth=6`,
        { headers: { Authorization: `Bearer ${authToken}` } }
      );
      const json = await res.json();
      if (res.ok) {
        setPathResult(json);
      } else {
        setError(json.detail || "Failed to find path");
      }
    } catch (err: any) {
      setError(err.message || "Error running path finder");
    } finally {
      setIsLoading(false);
    }
  };

  const handleRunValidation = async () => {
    try {
      setIsLoading(true);
      setError(null);
      const res = await fetch("/api/v3/knowledge-graph/validate", {
        method: "POST",
        headers: { Authorization: `Bearer ${authToken}` }
      });
      if (res.ok) {
        const json = await res.json();
        setValidationReport(json.report);
      }
    } catch (err: any) {
      setError(err.message || "Error validating graph");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSyncInventory = async () => {
    try {
      setIsLoading(true);
      setSyncMessage(null);
      const res = await fetch("/api/v3/knowledge-graph/projection/sync-inventory", {
        method: "POST",
        headers: { Authorization: `Bearer ${authToken}` }
      });
      const json = await res.json();
      if (res.ok) {
        setSyncMessage(json.message);
        loadInitialEntities();
      } else {
        setError(json.detail || "Sync failed");
      }
    } catch (err: any) {
      setError(err.message || "Sync error");
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 15 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 15 }}
          transition={{ duration: 0.2 }}
          className="relative w-full max-w-6xl h-[88vh] bg-[#0A0D12] border border-cyan-500/20 rounded-2xl shadow-2xl flex flex-col overflow-hidden text-zinc-100 font-mono"
        >
          {/* Top Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-[#0c1017]">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
                <Network className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-base font-semibold tracking-wide text-zinc-100 flex items-center gap-2">
                  OPERATIONAL KNOWLEDGE GRAPH
                  <span className="text-xs px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-400 font-mono border border-cyan-500/30">
                    V3 CONTEXT LAYER
                  </span>
                </h2>
                <p className="text-xs text-zinc-400">
                  Deterministic operational facts, bitemporal validity, provenance & graph traversals
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={handleSyncInventory}
                disabled={isLoading}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-xs text-cyan-300 border border-cyan-500/30 transition-colors"
                title="Project Datacore inventory into operational facts"
              >
                <Database className="w-3.5 h-3.5" />
                <span>Sync Inventory</span>
              </button>

              <button
                onClick={onClose}
                className="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-white/10 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          {/* Safety & Execution Isolation Banner */}
          <div className="px-6 py-2 bg-cyan-950/20 border-b border-cyan-500/15 flex items-center justify-between text-xs text-cyan-400/90">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-cyan-400" />
              <span>
                <strong>CARDINAL INVARIANT:</strong> Pure semantic & context layer. Zero execution capabilities. Zero Execution Gateway bypass.
              </span>
            </div>
            {syncMessage && <span className="text-emerald-400 font-semibold">{syncMessage}</span>}
          </div>

          {/* Main Layout Grid */}
          <div className="flex-1 grid grid-cols-12 overflow-hidden">
            {/* Left Column: Entity Selection (4 Cols) */}
            <div className="col-span-4 border-r border-white/10 flex flex-col bg-[#070A0E] overflow-hidden">
              <div className="p-3 border-b border-white/10">
                <div className="text-xs text-zinc-400 mb-1 flex items-center gap-1.5">
                  <Search className="w-3.5 h-3.5" />
                  <span>SELECT CANONICAL ENTITY</span>
                </div>
                <select
                  value={selectedEntityId}
                  onChange={(e) => setSelectedEntityId(e.target.value)}
                  className="w-full px-3 py-2 bg-[#0c1017] border border-white/10 rounded-lg text-xs text-zinc-200 focus:outline-none focus:border-cyan-500/50"
                >
                  {entities.map((e) => (
                    <option key={e.entity_id} value={e.entity_id}>
                      [{e.entity_type}] {e.display_name}
                    </option>
                  ))}
                </select>
              </div>

              {/* Entity Context Card */}
              {nodeData && (
                <div className="p-4 border-b border-white/10 bg-[#0B0F16] space-y-3">
                  <div>
                    <div className="text-[10px] text-zinc-400 uppercase tracking-wider">CANONICAL URN</div>
                    <div className="text-xs text-cyan-300 font-mono break-all">{nodeData.entity_id}</div>
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="p-2 rounded bg-black/40 border border-white/5">
                      <div className="text-[10px] text-zinc-400">OPERATIONAL STATUS</div>
                      <div className="font-semibold text-emerald-400">
                        {nodeData.operational_status || "IDLE"}
                      </div>
                    </div>
                    <div className="p-2 rounded bg-black/40 border border-white/5">
                      <div className="text-[10px] text-zinc-400">FRESHNESS</div>
                      <div className={`font-semibold ${
                        nodeData.freshness === "FRESH" ? "text-emerald-400" :
                        nodeData.freshness === "STALE" ? "text-amber-400" : "text-rose-400"
                      }`}>
                        {nodeData.freshness}
                      </div>
                    </div>
                  </div>

                  {nodeData.last_observed_at && (
                    <div className="text-[10px] text-zinc-400 flex items-center gap-1.5">
                      <Clock className="w-3 h-3 text-cyan-400" />
                      <span>Last Observed: {nodeData.last_observed_at}</span>
                    </div>
                  )}
                </div>
              )}

              {/* Navigation Tabs */}
              <div className="flex border-b border-white/10 bg-[#090C11] text-xs">
                <button
                  onClick={() => setActiveTab("facts")}
                  className={`flex-1 py-2.5 text-center font-medium border-b-2 transition-colors ${
                    activeTab === "facts"
                      ? "border-cyan-400 text-cyan-400 bg-cyan-500/5"
                      : "border-transparent text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  Facts ({nodeData?.active_facts?.length || 0})
                </button>
                <button
                  onClick={() => setActiveTab("neighbors")}
                  className={`flex-1 py-2.5 text-center font-medium border-b-2 transition-colors ${
                    activeTab === "neighbors"
                      ? "border-cyan-400 text-cyan-400 bg-cyan-500/5"
                      : "border-transparent text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  Neighbors ({neighbors.length})
                </button>
                <button
                  onClick={() => setActiveTab("path")}
                  className={`flex-1 py-2.5 text-center font-medium border-b-2 transition-colors ${
                    activeTab === "path"
                      ? "border-cyan-400 text-cyan-400 bg-cyan-500/5"
                      : "border-transparent text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  Path
                </button>
                <button
                  onClick={() => { setActiveTab("validation"); handleRunValidation(); }}
                  className={`flex-1 py-2.5 text-center font-medium border-b-2 transition-colors ${
                    activeTab === "validation"
                      ? "border-cyan-400 text-cyan-400 bg-cyan-500/5"
                      : "border-transparent text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  Audit
                </button>
              </div>

              {/* Left Sub-list */}
              <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
                {entities.map((e) => (
                  <button
                    key={e.entity_id}
                    onClick={() => setSelectedEntityId(e.entity_id)}
                    className={`w-full text-left p-2 rounded-lg border text-xs transition-all ${
                      selectedEntityId === e.entity_id
                        ? "bg-cyan-500/10 border-cyan-500/40 text-cyan-300"
                        : "bg-white/[0.02] border-white/5 text-zinc-300 hover:bg-white/[0.05]"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold truncate">{e.display_name}</span>
                      <span className="text-[10px] px-1.5 py-0.2 rounded bg-zinc-800 text-zinc-400">
                        {e.entity_type}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* Right Column: Context Tab Content (8 Cols) */}
            <div className="col-span-8 flex flex-col bg-[#0A0D12] overflow-hidden">
              <div className="flex-1 overflow-y-auto p-6 space-y-4">
                {error && (
                  <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4" />
                    <span>{error}</span>
                  </div>
                )}

                {/* TAB 1: OPERATIONAL FACTS */}
                {activeTab === "facts" && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <h3 className="text-xs font-semibold text-zinc-300 flex items-center gap-1.5">
                        <Activity className="w-4 h-4 text-cyan-400" />
                        <span>ACTIVE OPERATIONAL FACTS & STATE</span>
                      </h3>
                      <span className="text-xs text-zinc-400">
                        {nodeData?.active_facts?.length || 0} recorded
                      </span>
                    </div>

                    {(!nodeData?.active_facts || nodeData.active_facts.length === 0) ? (
                      <div className="p-8 rounded-xl border border-white/5 bg-white/[0.01] text-center text-zinc-400 text-xs">
                        No active operational facts currently associated with this entity.
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {nodeData.active_facts.map((fact) => (
                          <div
                            key={fact.fact_id}
                            className="p-3 rounded-xl border border-white/10 bg-[#0d121a] space-y-2"
                          >
                            <div className="flex items-center justify-between">
                              <span className="text-xs font-bold text-cyan-300 flex items-center gap-1.5">
                                <Tag className="w-3.5 h-3.5 text-cyan-400" />
                                {fact.predicate}
                              </span>
                              <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                                {fact.status}
                              </span>
                            </div>

                            <div className="text-sm font-mono text-zinc-100 bg-black/40 p-2 rounded border border-white/5">
                              {typeof fact.value === "object" ? JSON.stringify(fact.value) : String(fact.value)}
                              {fact.unit && <span className="text-xs text-zinc-400 ml-1.5">({fact.unit})</span>}
                            </div>

                            <div className="grid grid-cols-3 gap-2 text-[10px] text-zinc-400 pt-1 border-t border-white/5">
                              <div>Source: <span className="text-zinc-300">{fact.source_type} ({fact.source_id})</span></div>
                              <div>Observed: <span className="text-zinc-300">{fact.observed_at.substring(0, 19)}</span></div>
                              <div>Valid From: <span className="text-zinc-300">{fact.valid_from.substring(0, 19)}</span></div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* TAB 2: GRAPH NEIGHBORS */}
                {activeTab === "neighbors" && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <h3 className="text-xs font-semibold text-zinc-300 flex items-center gap-1.5">
                        <Network className="w-4 h-4 text-cyan-400" />
                        <span>CONNECTED 1-HOP NEIGHBORS (ONTOLOGY + OPERATIONAL)</span>
                      </h3>
                      <span className="text-xs text-zinc-400">{neighbors.length} connected</span>
                    </div>

                    {neighbors.length === 0 ? (
                      <div className="p-8 rounded-xl border border-white/5 bg-white/[0.01] text-center text-zinc-400 text-xs">
                        No graph neighbors found for this entity.
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {neighbors.map((nb, i) => (
                          <div
                            key={i}
                            className="p-3 rounded-xl border border-white/10 bg-[#0d121a] flex items-center justify-between"
                          >
                            <div className="space-y-1">
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-bold text-zinc-100">{nb.display_name}</span>
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400">
                                  {nb.entity_type}
                                </span>
                              </div>
                              <div className="text-[10px] text-zinc-400 font-mono">{nb.entity_id}</div>
                            </div>

                            <div className="flex items-center gap-2">
                              <span className="text-[10px] px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-300 border border-cyan-500/30">
                                {nb.relationship_type} ({nb.direction})
                              </span>
                              <span className="text-[10px] px-2 py-0.5 rounded bg-zinc-800 text-zinc-400">
                                {nb.edge_source}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* TAB 3: PATH FINDER */}
                {activeTab === "path" && (
                  <div className="space-y-4">
                    <h3 className="text-xs font-semibold text-zinc-300 flex items-center gap-1.5">
                      <Compass className="w-4 h-4 text-cyan-400" />
                      <span>DETERMINISTIC SHORTEST PATH FINDER (BFS)</span>
                    </h3>

                    <div className="p-4 rounded-xl border border-white/10 bg-[#0d121a] space-y-3">
                      <div className="text-xs text-zinc-400">Target Entity URN:</div>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={targetEntityId}
                          onChange={(e) => setTargetEntityId(e.target.value)}
                          placeholder="e.g. sensor:plant_mumbai:vib_sensor_01"
                          className="flex-1 px-3 py-2 bg-black/40 border border-white/10 rounded-lg text-xs text-zinc-200 focus:outline-none focus:border-cyan-500"
                        />
                        <button
                          onClick={handleFindPath}
                          disabled={isLoading || !targetEntityId}
                          className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-black font-semibold text-xs transition-colors"
                        >
                          Find Path
                        </button>
                      </div>
                    </div>

                    {pathResult && (
                      <div className="p-4 rounded-xl border border-white/10 bg-[#0d121a] space-y-3">
                        <div className="flex items-center justify-between text-xs">
                          <span className="font-semibold text-cyan-400">Traversal Result:</span>
                          <span className="text-zinc-400">
                            {pathResult.found ? `Path found (Depth: ${pathResult.data?.depth})` : "No path exists"}
                          </span>
                        </div>

                        {pathResult.found && pathResult.data && (
                          <div className="space-y-2 pt-2">
                            {pathResult.data.path.map((step: string, idx: number) => (
                              <div key={idx} className="flex items-center gap-2 text-xs">
                                <span className="w-6 h-6 rounded-full bg-cyan-500/20 text-cyan-400 flex items-center justify-center font-bold text-[10px]">
                                  {idx + 1}
                                </span>
                                <span className="font-mono text-zinc-200">{step}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* TAB 4: CONSISTENCY AUDIT */}
                {activeTab === "validation" && (
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <h3 className="text-xs font-semibold text-zinc-300 flex items-center gap-1.5">
                        <CheckCircle2 className="w-4 h-4 text-cyan-400" />
                        <span>GRAPH CONSISTENCY & VALIDATION AUDIT</span>
                      </h3>
                      <button
                        onClick={handleRunValidation}
                        disabled={isLoading}
                        className="px-3 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-xs text-cyan-300 border border-cyan-500/30 flex items-center gap-1.5"
                      >
                        <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
                        <span>Re-Audit</span>
                      </button>
                    </div>

                    {validationReport && (
                      <div className="space-y-3">
                        <div className="grid grid-cols-3 gap-3">
                          <div className="p-3 rounded-xl bg-[#0d121a] border border-white/10 text-xs">
                            <div className="text-[10px] text-zinc-400">STATUS</div>
                            <div className={`font-bold text-sm ${validationReport.is_valid ? "text-emerald-400" : "text-rose-400"}`}>
                              {validationReport.is_valid ? "CONSISTENT" : "ISSUES DETECTED"}
                            </div>
                          </div>
                          <div className="p-3 rounded-xl bg-[#0d121a] border border-white/10 text-xs">
                            <div className="text-[10px] text-zinc-400">ERRORS</div>
                            <div className="font-bold text-sm text-rose-400">{validationReport.error_count}</div>
                          </div>
                          <div className="p-3 rounded-xl bg-[#0d121a] border border-white/10 text-xs">
                            <div className="text-[10px] text-zinc-400">WARNINGS</div>
                            <div className="font-bold text-sm text-amber-400">{validationReport.warning_count}</div>
                          </div>
                        </div>

                        <div className="space-y-2">
                          {validationReport.issues.length === 0 ? (
                            <div className="p-6 rounded-xl border border-emerald-500/20 bg-emerald-500/5 text-center text-xs text-emerald-300">
                              Zero consistency errors or dangling edges discovered. Knowledge graph is healthy.
                            </div>
                          ) : (
                            validationReport.issues.map((issue, idx) => (
                              <div
                                key={idx}
                                className={`p-3 rounded-xl border text-xs ${
                                  issue.severity === "ERROR"
                                    ? "bg-rose-500/10 border-rose-500/30 text-rose-300"
                                    : "bg-amber-500/10 border-amber-500/30 text-amber-300"
                                }`}
                              >
                                <div className="font-semibold">{issue.issue_type}</div>
                                <div>{issue.message}</div>
                              </div>
                            ))
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
