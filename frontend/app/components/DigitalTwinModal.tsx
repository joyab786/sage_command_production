"use client";

import React, { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  X,
  Layers,
  Clock,
  Camera,
  GitBranch,
  RefreshCw,
  Search,
  AlertTriangle,
  CheckCircle2,
  Activity,
  History,
  Info,
  Server,
  Zap,
} from "lucide-react";

interface TwinStateProperty {
  property_name: string;
  value_type: string;
  value: any;
  unit?: string | null;
  classification: string;
  confidence: string;
  source_type: string;
  source_id: string;
  recorded_at: string;
  effective_at: string;
  conflict_state: string;
}

interface TwinEntity {
  entity_id: string;
  entity_type: string;
  tenant_id: string;
  version: number;
  properties: { [key: string]: TwinStateProperty };
  created_at: string;
  updated_at: string;
  freshness_state: string;
}

interface TwinStateVersion {
  version_id: string;
  entity_id: string;
  tenant_id: string;
  version: number;
  properties: { [key: string]: TwinStateProperty };
  recorded_at: string;
}

interface TwinSnapshot {
  snapshot_id: string;
  tenant_id: string;
  name: string;
  description?: string;
  snapshot_time: string;
  created_by: string;
  entity_ids: string[];
}

interface DigitalTwinModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialEntityId?: string;
}

export default function DigitalTwinModal({ isOpen, onClose, initialEntityId }: DigitalTwinModalProps) {
  const [activeTab, setActiveTab] = useState<"current" | "history" | "snapshots">("current");
  const [entities, setEntities] = useState<any[]>([]);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(initialEntityId || null);
  const [searchQuery, setSearchQuery] = useState("");
  
  // Data states
  const [twinData, setTwinData] = useState<TwinEntity | null>(null);
  const [twinHistory, setTwinHistory] = useState<TwinStateVersion[]>([]);
  
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch twin eligible entities from ontology (simplified for UI)
  useEffect(() => {
    if (isOpen) {
      const fetchEntities = async () => {
        try {
          // Fetch ontology entities, then filter for twin eligible types
          const res = await fetch("/api/v3/ontology/entities");
          if (!res.ok) throw new Error("Failed to load entities");
          const data = await res.json();
          
          const eligibleTypes = [
            "MACHINE", "EQUIPMENT", "ROBOT", "SENSOR", "ACTUATOR",
            "PLC", "CONTROLLER", "PRODUCTION_LINE", "WORK_CELL",
            "STORAGE_LOCATION", "INVENTORY_ITEM", "ENERGY_RESOURCE", "UTILITY"
          ];
          
          const twinEligible = (data.data || []).filter((e: any) => 
            eligibleTypes.includes(e.entity_type)
          );
          
          setEntities(twinEligible);
          
          if (!selectedEntityId && twinEligible.length > 0) {
            setSelectedEntityId(twinEligible[0].entity_id);
          }
        } catch (err: any) {
          setError(err.message || "Failed to load entities");
        }
      };
      
      fetchEntities();
    }
  }, [isOpen]);

  // Fetch Twin Data when selected entity changes
  useEffect(() => {
    if (isOpen && selectedEntityId) {
      fetchTwinData(selectedEntityId);
    }
  }, [isOpen, selectedEntityId]);

  const fetchTwinData = async (entityId: string) => {
    setIsLoading(true);
    setError(null);
    setTwinData(null);
    setTwinHistory([]);
    try {
      // Fetch current state
      const res = await fetch(`/api/v3/digital-twin/entities/${entityId}`);
      if (!res.ok) {
        if (res.status === 404) {
          setError(`No digital twin state initialized for ${entityId}`);
        } else {
          throw new Error("Failed to fetch digital twin state");
        }
      } else {
        const data = await res.json();
        setTwinData(data.data);
      }
      
      // Fetch history in parallel if we switch to history tab
      const histRes = await fetch(`/api/v3/digital-twin/entities/${entityId}/history`);
      if (histRes.ok) {
        const histData = await histRes.json();
        setTwinHistory(histData.data || []);
      }
    } catch (err: any) {
      setError(err.message || "An error occurred");
    } finally {
      setIsLoading(false);
    }
  };

  const filteredEntities = entities.filter(
    (e) =>
      e.display_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      e.entity_id.toLowerCase().includes(searchQuery.toLowerCase())
  );

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/60 backdrop-blur-sm">
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 10 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 10 }}
          transition={{ type: "spring", damping: 25, stiffness: 300 }}
          className="w-full max-w-6xl h-[85vh] bg-[#0A0D12] border border-white/10 rounded-2xl shadow-2xl flex flex-col overflow-hidden"
        >
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-white/10 bg-[#0d121a]">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-indigo-500/20 rounded-lg">
                <Layers className="w-5 h-5 text-indigo-400" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-white">Digital Twin Foundation</h2>
                <p className="text-xs text-zinc-400">Deterministic Virtual Operational State</p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 text-zinc-400 hover:text-white transition-colors rounded-lg hover:bg-white/5"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          <div className="flex-1 grid grid-cols-12 overflow-hidden">
            {/* Left Sidebar (4 Cols) */}
            <div className="col-span-4 border-r border-white/10 flex flex-col bg-[#0d121a]/50">
              {/* Search */}
              <div className="p-4 border-b border-white/5">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
                  <input
                    type="text"
                    placeholder="Search Twin Entities..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full bg-[#1A1F29] border border-white/10 rounded-lg pl-9 pr-4 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/50 transition-all"
                  />
                </div>
              </div>

              {/* Entity List */}
              <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
                {filteredEntities.map((e) => (
                  <button
                    key={e.entity_id}
                    onClick={() => setSelectedEntityId(e.entity_id)}
                    className={`w-full text-left p-2 rounded-lg border text-xs transition-all ${
                      selectedEntityId === e.entity_id
                        ? "bg-indigo-500/10 border-indigo-500/40 text-indigo-300"
                        : "bg-white/[0.02] border-white/5 text-zinc-300 hover:bg-white/[0.05]"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold truncate">{e.display_name}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400">
                        {e.entity_type}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* Right Main Area (8 Cols) */}
            <div className="col-span-8 flex flex-col bg-[#0A0D12] overflow-hidden">
              {/* Tabs */}
              <div className="flex items-center border-b border-white/5 bg-[#0d121a]">
                <button
                  onClick={() => setActiveTab("current")}
                  className={`flex-1 flex items-center justify-center gap-2 py-3 text-xs font-medium transition-colors border-b-2 ${
                    activeTab === "current"
                      ? "text-indigo-400 border-indigo-500 bg-indigo-500/5"
                      : "text-zinc-400 border-transparent hover:text-zinc-300 hover:bg-white/[0.02]"
                  }`}
                >
                  <Activity className="w-4 h-4" />
                  Current State
                </button>
                <button
                  onClick={() => setActiveTab("history")}
                  className={`flex-1 flex items-center justify-center gap-2 py-3 text-xs font-medium transition-colors border-b-2 ${
                    activeTab === "history"
                      ? "text-indigo-400 border-indigo-500 bg-indigo-500/5"
                      : "text-zinc-400 border-transparent hover:text-zinc-300 hover:bg-white/[0.02]"
                  }`}
                >
                  <History className="w-4 h-4" />
                  State History
                </button>
                <button
                  onClick={() => setActiveTab("snapshots")}
                  className={`flex-1 flex items-center justify-center gap-2 py-3 text-xs font-medium transition-colors border-b-2 ${
                    activeTab === "snapshots"
                      ? "text-indigo-400 border-indigo-500 bg-indigo-500/5"
                      : "text-zinc-400 border-transparent hover:text-zinc-300 hover:bg-white/[0.02]"
                  }`}
                >
                  <Camera className="w-4 h-4" />
                  Snapshots & Scenarios
                </button>
              </div>

              {/* Tab Content */}
              <div className="flex-1 overflow-y-auto p-6 relative">
                {isLoading && (
                  <div className="absolute inset-0 z-10 bg-[#0A0D12]/80 backdrop-blur-sm flex items-center justify-center">
                    <RefreshCw className="w-8 h-8 text-indigo-500 animate-spin" />
                  </div>
                )}

                {error && (
                  <div className="mb-4 p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4" />
                    <span>{error}</span>
                  </div>
                )}

                {/* CURRENT STATE TAB */}
                {activeTab === "current" && twinData && (
                  <div className="space-y-6">
                    {/* Meta */}
                    <div className="flex items-center justify-between p-4 bg-[#0d121a] border border-white/5 rounded-xl">
                      <div className="space-y-1">
                        <div className="text-xs text-zinc-500">Twin Version</div>
                        <div className="text-sm font-mono text-zinc-300 flex items-center gap-2">
                          <GitBranch className="w-4 h-4 text-indigo-400" />
                          v{twinData.version}
                        </div>
                      </div>
                      <div className="space-y-1 text-right">
                        <div className="text-xs text-zinc-500">Freshness</div>
                        <div className="text-sm font-medium">
                          {twinData.freshness_state === "FRESH" ? (
                            <span className="text-emerald-400 flex items-center justify-end gap-1"><CheckCircle2 className="w-4 h-4"/> FRESH</span>
                          ) : (
                            <span className="text-amber-400 flex items-center justify-end gap-1"><AlertTriangle className="w-4 h-4"/> {twinData.freshness_state}</span>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Properties */}
                    <div>
                      <h3 className="text-xs font-semibold text-zinc-400 mb-3 flex items-center gap-2">
                        <Zap className="w-4 h-4 text-amber-400" />
                        STATE PROPERTIES
                      </h3>
                      
                      {Object.keys(twinData.properties).length === 0 ? (
                        <div className="p-8 text-center border border-white/5 rounded-xl bg-white/[0.02] text-zinc-500 text-xs">
                          No state properties ingested for this twin.
                        </div>
                      ) : (
                        <div className="grid grid-cols-2 gap-3">
                          {Object.values(twinData.properties).map((prop: TwinStateProperty, i: number) => (
                            <div key={i} className="p-4 bg-[#0d121a] border border-white/5 rounded-xl flex flex-col gap-2">
                              <div className="flex items-center justify-between">
                                <span className="text-xs font-medium text-zinc-300">{prop.property_name}</span>
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/5 text-zinc-400 font-mono">
                                  {prop.value_type}
                                </span>
                              </div>
                              <div className="text-xl font-bold text-white flex items-baseline gap-1">
                                {String(prop.value)}
                                {prop.unit && <span className="text-xs text-zinc-500 font-normal">{prop.unit}</span>}
                              </div>
                              <div className="flex items-center justify-between mt-1 pt-2 border-t border-white/5">
                                <span className="text-[10px] text-zinc-500 flex items-center gap-1">
                                  <Server className="w-3 h-3" />
                                  {prop.source_type}
                                </span>
                                <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                                  prop.classification === 'OBSERVED' ? 'bg-emerald-500/20 text-emerald-300' :
                                  prop.classification === 'SIMULATED' ? 'bg-indigo-500/20 text-indigo-300' :
                                  'bg-zinc-800 text-zinc-300'
                                }`}>
                                  {prop.classification}
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* HISTORY TAB */}
                {activeTab === "history" && (
                  <div className="space-y-4">
                    {twinHistory.length === 0 ? (
                      <div className="p-8 text-center border border-white/5 rounded-xl bg-white/[0.02] text-zinc-500 text-xs">
                        No historical versions available.
                      </div>
                    ) : (
                      <div className="relative border-l border-white/10 ml-3 pl-4 space-y-6">
                        {twinHistory.map((ver, idx) => (
                          <div key={ver.version_id} className="relative">
                            <div className="absolute -left-[21px] top-1.5 w-2 h-2 bg-indigo-500 rounded-full ring-4 ring-[#0A0D12]" />
                            <div className="p-4 bg-[#0d121a] border border-white/5 rounded-xl">
                              <div className="flex items-center justify-between mb-3">
                                <div className="flex items-center gap-2">
                                  <span className="text-xs font-bold text-indigo-400 font-mono">v{ver.version}</span>
                                  <span className="text-xs text-zinc-500">{new Date(ver.recorded_at).toLocaleString()}</span>
                                </div>
                                <span className="text-[10px] text-zinc-500 font-mono">{ver.version_id.substring(0,8)}</span>
                              </div>
                              
                              <div className="space-y-2">
                                {Object.values(ver.properties).map((prop, i) => (
                                  <div key={i} className="flex justify-between items-center text-xs p-2 bg-white/[0.02] rounded">
                                    <span className="text-zinc-400">{prop.property_name}</span>
                                    <span className="text-zinc-200 font-mono">{String(prop.value)} {prop.unit}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* SNAPSHOTS TAB */}
                {activeTab === "snapshots" && (
                  <div className="space-y-4">
                    <div className="p-8 text-center border border-dashed border-white/10 rounded-xl bg-[#0d121a] text-zinc-500 text-xs">
                      <Camera className="w-8 h-8 text-zinc-600 mx-auto mb-3" />
                      <p>Snapshot creation and Scenario simulations are accessible via the Digital Twin SDK.</p>
                      <p className="mt-2 text-[10px] text-indigo-400/70">UI implementation coming in next iteration.</p>
                    </div>
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
