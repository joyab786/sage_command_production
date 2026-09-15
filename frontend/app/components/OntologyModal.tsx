"use client";

import React, { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  X,
  Layers,
  Search,
  Filter,
  RefreshCw,
  Cpu,
  Radio,
  Building2,
  Box,
  Tag,
  Clock,
  ArrowRight,
  ShieldCheck,
  AlertTriangle
} from "lucide-react";

interface OntologyEntity {
  entity_id: string;
  entity_type: string;
  canonical_name: string;
  display_name: string;
  tenant_id: string;
  workspace_id: string;
  plant_id?: string | null;
  external_ids: Record<string, string>;
  attributes: Record<string, any>;
  metadata: Record<string, any>;
  status: string;
  source: string;
  version: number;
  created_at: string;
  updated_at: string;
}

interface OntologyRelationship {
  relationship_id: string;
  relationship_type: string;
  source_entity_id: string;
  target_entity_id: string;
  confidence: string;
  source: string;
}

interface OntologyModalProps {
  isOpen: boolean;
  onClose: () => void;
  token?: string;
}

export default function OntologyModal({ isOpen, onClose, token }: OntologyModalProps) {
  const [entities, setEntities] = useState<OntologyEntity[]>([]);
  const [selectedEntity, setSelectedEntity] = useState<OntologyEntity | null>(null);
  const [relationships, setRelationships] = useState<OntologyRelationship[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("ALL");

  const authToken = token || "dev_token";

  useEffect(() => {
    if (isOpen) {
      fetchEntities();
    }
  }, [isOpen]);

  useEffect(() => {
    if (selectedEntity) {
      fetchRelationships(selectedEntity.entity_id);
    } else {
      setRelationships([]);
    }
  }, [selectedEntity]);

  const fetchEntities = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch("http://localhost:8000/api/v3/ontology/entities?limit=100", {
        headers: {
          Authorization: `Bearer ${authToken}`,
        },
      });
      if (!res.ok) {
        throw new Error(`Failed to load ontology entities (HTTP ${res.status})`);
      }
      const data = await res.json();
      const list = data.data || [];
      setEntities(list);
      if (list.length > 0 && !selectedEntity) {
        setSelectedEntity(list[0]);
      }
    } catch (err: any) {
      setError(err.message || "Failed to fetch ontology entities");
    } finally {
      setIsLoading(false);
    }
  };

  const fetchRelationships = async (entityId: string) => {
    try {
      const res = await fetch(`http://localhost:8000/api/v3/ontology/entities/${encodeURIComponent(entityId)}/relationships`, {
        headers: {
          Authorization: `Bearer ${authToken}`,
        },
      });
      if (res.ok) {
        const data = await res.json();
        setRelationships(data.data || []);
      }
    } catch {
      setRelationships([]);
    }
  };

  const filteredEntities = entities.filter((e) => {
    const matchesSearch =
      e.canonical_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      e.entity_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      e.display_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      Object.values(e.external_ids).some((v) => v.toLowerCase().includes(searchQuery.toLowerCase()));
    const matchesType = typeFilter === "ALL" || e.entity_type === typeFilter;
    return matchesSearch && matchesType;
  });

  const entityTypes = ["ALL", ...Array.from(new Set(entities.map((e) => e.entity_type)))];

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 15 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 15 }}
            transition={{ duration: 0.2 }}
            className="w-full max-w-6xl h-[85vh] bg-[#0c0d10] border border-cyan-500/20 rounded-xl flex flex-col shadow-2xl overflow-hidden font-sans"
          >
            {/* Modal Header */}
            <div className="h-16 px-6 border-b border-white/10 flex items-center justify-between bg-black/40">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center">
                  <Layers className="w-5 h-5 text-cyan-400" />
                </div>
                <div>
                  <h2 className="text-sm font-mono uppercase tracking-widest text-cyan-400 font-bold flex items-center gap-2">
                    Industrial Ontology Explorer
                    <span className="text-[10px] px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                      V3 Semantic Truth
                    </span>
                  </h2>
                  <p className="text-xs text-gray-400">Canonical identity mapping & semantic relationship graph</p>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={fetchEntities}
                  disabled={isLoading}
                  className="p-2 text-gray-400 hover:text-white rounded hover:bg-white/5 transition-colors"
                  title="Refresh"
                >
                  <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
                </button>
                <button
                  type="button"
                  onClick={onClose}
                  className="p-2 text-gray-400 hover:text-white rounded hover:bg-white/5 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Error Banner */}
            {error && (
              <div className="px-6 py-2.5 bg-red-500/10 border-b border-red-500/20 text-red-400 text-xs flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {/* Search & Filter Bar */}
            <div className="px-6 py-3 border-b border-white/5 bg-black/20 flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-2 flex-1 max-w-md bg-black/40 border border-white/10 rounded-lg px-3 py-1.5 focus-within:border-cyan-500/50">
                <Search className="w-4 h-4 text-gray-400" />
                <input
                  type="text"
                  placeholder="Search by canonical ID, name, or external ID (SAP, MES)..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="bg-transparent text-xs text-gray-200 placeholder-gray-500 outline-none w-full font-mono"
                />
              </div>

              <div className="flex items-center gap-2">
                <Filter className="w-3.5 h-3.5 text-gray-400" />
                <span className="text-[11px] text-gray-400 uppercase font-mono">Type:</span>
                <select
                  value={typeFilter}
                  onChange={(e) => setTypeFilter(e.target.value)}
                  className="bg-black/60 border border-white/10 rounded px-2.5 py-1 text-xs text-gray-300 font-mono focus:border-cyan-500/50 outline-none"
                >
                  {entityTypes.map((t) => (
                    <option key={t} value={t} className="bg-zinc-900 text-gray-200">
                      {t}
                    </option>
                  ))}
                </select>
                <span className="text-[10px] text-gray-500 font-mono ml-2">
                  {filteredEntities.length} entities
                </span>
              </div>
            </div>

            {/* Main Content: Split Master-Detail */}
            <div className="flex-1 flex overflow-hidden">
              {/* Left Pane: Entity List */}
              <div className="w-2/5 border-r border-white/5 overflow-y-auto p-4 space-y-2">
                {isLoading && entities.length === 0 ? (
                  <div className="h-full flex items-center justify-center text-xs text-gray-500 font-mono">
                    <RefreshCw className="w-5 h-5 animate-spin mr-2 text-cyan-400" /> Loading ontology entities...
                  </div>
                ) : filteredEntities.length === 0 ? (
                  <div className="h-full flex flex-col items-center justify-center text-xs text-gray-500 font-mono p-6 text-center">
                    <Box className="w-8 h-8 text-gray-600 mb-2" />
                    <span>No canonical entities found matching criteria.</span>
                  </div>
                ) : (
                  filteredEntities.map((entity) => {
                    const isSelected = selectedEntity?.entity_id === entity.entity_id;
                    return (
                      <button
                        type="button"
                        key={entity.entity_id}
                        onClick={() => setSelectedEntity(entity)}
                        className={`w-full text-left p-3 rounded-lg border transition-all ${
                          isSelected
                            ? "bg-cyan-950/20 border-cyan-500/40 shadow-sm"
                            : "bg-black/20 border-white/5 hover:border-white/15 hover:bg-white/[0.02]"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2 mb-1">
                          <span className="text-xs font-semibold text-gray-200 truncate">
                            {entity.display_name}
                          </span>
                          <span className="text-[10px] px-2 py-0.5 rounded font-mono font-bold bg-white/5 text-gray-400 border border-white/10">
                            {entity.entity_type}
                          </span>
                        </div>
                        <div className="text-[11px] font-mono text-cyan-400/80 truncate mb-1.5">
                          {entity.entity_id}
                        </div>
                        <div className="flex items-center justify-between text-[10px] text-gray-500 font-mono">
                          <span>{entity.plant_id || "global"}</span>
                          <span
                            className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                              entity.status === "ACTIVE"
                                ? "bg-emerald-500/10 text-emerald-400"
                                : entity.status === "CONFLICT"
                                ? "bg-red-500/10 text-red-400"
                                : "bg-zinc-500/10 text-gray-400"
                            }`}
                          >
                            {entity.status}
                          </span>
                        </div>
                      </button>
                    );
                  })
                )}
              </div>

              {/* Right Pane: Entity Details & Relationships */}
              <div className="w-3/5 overflow-y-auto p-6 bg-black/10">
                {selectedEntity ? (
                  <div className="space-y-6">
                    {/* Header Info */}
                    <div className="border-b border-white/10 pb-4">
                      <div className="flex items-center justify-between gap-4 mb-2">
                        <h3 className="text-lg font-bold text-white tracking-tight">
                          {selectedEntity.display_name}
                        </h3>
                        <span className="text-xs font-mono font-bold px-2.5 py-1 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/30">
                          {selectedEntity.entity_type}
                        </span>
                      </div>
                      <div className="text-xs font-mono text-cyan-300 bg-cyan-950/30 border border-cyan-500/20 px-3 py-1.5 rounded break-all">
                        {selectedEntity.entity_id}
                      </div>
                    </div>

                    {/* Meta Grid */}
                    <div className="grid grid-cols-3 gap-3 font-mono text-xs">
                      <div className="bg-black/30 border border-white/5 p-2.5 rounded">
                        <span className="text-gray-500 block text-[10px] uppercase">Lifecycle Status</span>
                        <span className="font-bold text-emerald-400">{selectedEntity.status}</span>
                      </div>
                      <div className="bg-black/30 border border-white/5 p-2.5 rounded">
                        <span className="text-gray-500 block text-[10px] uppercase">Provenance Source</span>
                        <span className="text-gray-300">{selectedEntity.source}</span>
                      </div>
                      <div className="bg-black/30 border border-white/5 p-2.5 rounded">
                        <span className="text-gray-500 block text-[10px] uppercase">Schema Version</span>
                        <span className="text-cyan-400">v{selectedEntity.version}</span>
                      </div>
                    </div>

                    {/* External ID Mappings */}
                    <div>
                      <h4 className="text-xs font-mono uppercase tracking-wider text-gray-400 mb-2 flex items-center gap-1.5">
                        <Tag className="w-3.5 h-3.5 text-cyan-400" />
                        External Identifiers (MES / SCADA / ERP / PLC)
                      </h4>
                      {Object.keys(selectedEntity.external_ids).length > 0 ? (
                        <div className="grid grid-cols-2 gap-2 font-mono text-xs">
                          {Object.entries(selectedEntity.external_ids).map(([sys, id]) => (
                            <div
                              key={sys}
                              className="flex items-center justify-between p-2 bg-black/40 border border-white/10 rounded"
                            >
                              <span className="text-gray-400 font-bold">{sys}:</span>
                              <span className="text-cyan-300 font-semibold">{id}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-gray-500 font-mono italic">
                          No external system mappings registered.
                        </p>
                      )}
                    </div>

                    {/* Attributes */}
                    {Object.keys(selectedEntity.attributes).length > 0 && (
                      <div>
                        <h4 className="text-xs font-mono uppercase tracking-wider text-gray-400 mb-2 flex items-center gap-1.5">
                          <Cpu className="w-3.5 h-3.5 text-cyan-400" />
                          Entity Attributes & Specifications
                        </h4>
                        <div className="bg-black/40 border border-white/5 rounded-lg p-3 text-xs font-mono space-y-1 max-h-40 overflow-y-auto">
                          {Object.entries(selectedEntity.attributes).map(([k, v]) => (
                            <div key={k} className="flex justify-between py-0.5 border-b border-white/[0.03]">
                              <span className="text-gray-400">{k}:</span>
                              <span className="text-gray-200 font-semibold">{String(v)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Semantic Relationships */}
                    <div>
                      <h4 className="text-xs font-mono uppercase tracking-wider text-gray-400 mb-2 flex items-center gap-1.5">
                        <Radio className="w-3.5 h-3.5 text-cyan-400" />
                        Connected Semantic Relationships ({relationships.length})
                      </h4>
                      {relationships.length > 0 ? (
                        <div className="space-y-2 max-h-48 overflow-y-auto">
                          {relationships.map((rel) => {
                            const isSource = rel.source_entity_id === selectedEntity.entity_id;
                            return (
                              <div
                                key={rel.relationship_id}
                                className="p-2.5 bg-black/40 border border-white/5 rounded text-xs font-mono flex items-center justify-between gap-3"
                              >
                                <div className="flex items-center gap-2 truncate">
                                  <span className="px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 text-[10px] font-bold border border-cyan-500/20">
                                    {rel.relationship_type}
                                  </span>
                                  <ArrowRight className="w-3 h-3 text-gray-500 shrink-0" />
                                  <span className="text-gray-300 truncate">
                                    {isSource ? rel.target_entity_id : rel.source_entity_id}
                                  </span>
                                </div>
                                <span className="text-[9px] px-1.5 py-0.5 bg-white/5 rounded text-gray-400 shrink-0">
                                  {rel.confidence}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      ) : (
                        <p className="text-xs text-gray-500 font-mono italic">
                          No relationship edges connected to this entity.
                        </p>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="h-full flex items-center justify-center text-xs text-gray-500 font-mono">
                    Select an entity on the left to inspect canonical details.
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
