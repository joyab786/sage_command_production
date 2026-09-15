"use client";
import React, { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, ShieldAlert, CheckCircle, AlertTriangle, Shield, Search, RefreshCw, AlertOctagon } from "lucide-react";

interface DataQualityModalProps {
  isOpen: boolean;
  onClose: () => void;
  token?: string;
}

export default function DataQualityModal({ isOpen, onClose, token = "manager_token" }: DataQualityModalProps) {
  const [activeTab, setActiveTab] = useState<"assessments" | "issues" | "rules">("assessments");
  const [assessments, setAssessments] = useState<any[]>([]);
  const [issues, setIssues] = useState<any[]>([]);
  const [rules, setRules] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      fetchData();
    }
  }, [isOpen, activeTab]);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const headers = { Authorization: `Bearer ${token}` };
      
      if (activeTab === "assessments") {
        const res = await fetch("http://localhost:8000/api/v3/data-quality/assessments", { headers });
        if (!res.ok) throw new Error("Failed to fetch assessments");
        setAssessments(await res.json());
      } else if (activeTab === "issues") {
        const res = await fetch("http://localhost:8000/api/v3/data-quality/issues", { headers });
        if (!res.ok) throw new Error("Failed to fetch issues");
        const data = await res.json();
        setIssues(data.issues || []);
      } else if (activeTab === "rules") {
        const res = await fetch("http://localhost:8000/api/v3/data-quality/rules", { headers });
        if (!res.ok) throw new Error("Failed to fetch rules");
        setRules(await res.json());
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const runAssessment = async () => {
    setRunning(true);
    setError(null);
    try {
      const res = await fetch("http://localhost:8000/api/v3/data-quality/assess", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          scope: {
            tenant_id: "tenant_55",
            plant_id: "plant_1"
          }
        })
      });
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Assessment failed");
      }
      
      await fetchData();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setRunning(false);
    }
  };

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="absolute inset-0 bg-black/80 backdrop-blur-sm"
          onClick={onClose}
        />

        {/* Modal Content */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 20 }}
          className="relative w-full max-w-5xl bg-[#0a0a0a] border border-white/10 rounded-xl shadow-2xl flex flex-col h-[85vh] overflow-hidden"
        >
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-white/10 bg-black/40">
            <div className="flex items-center gap-3">
              <ShieldAlert className="w-5 h-5 text-emerald-400" />
              <div>
                <h2 className="text-sm font-bold text-white uppercase tracking-wider">Data Quality Engine</h2>
                <p className="text-[10px] text-gray-400 font-mono">Semantic Health & Observational Integrity (Prompt 14)</p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <button
                onClick={runAssessment}
                disabled={running}
                className="px-4 py-1.5 bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 rounded text-xs font-bold uppercase tracking-wider hover:bg-emerald-500/20 disabled:opacity-50 flex items-center gap-2"
              >
                {running ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Search className="w-3 h-3" />}
                {running ? "Assessing..." : "Run Assessment"}
              </button>
              <button
                onClick={onClose}
                className="p-1.5 text-gray-400 hover:text-white rounded-md hover:bg-white/10 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Navigation */}
          <div className="flex px-4 border-b border-white/10 bg-black/20">
            {["assessments", "issues", "rules"].map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab as any)}
                className={`px-4 py-3 text-xs font-bold uppercase tracking-wider transition-colors relative ${
                  activeTab === tab ? "text-emerald-400" : "text-gray-500 hover:text-gray-300"
                }`}
              >
                {tab}
                {activeTab === tab && (
                  <motion.div
                    layoutId="dq-active-tab"
                    className="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-500"
                  />
                )}
              </button>
            ))}
          </div>

          {/* Content Area */}
          <div className="flex-1 overflow-y-auto p-4 bg-gradient-to-b from-black/20 to-transparent">
            {error && (
              <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded text-red-400 text-xs font-mono">
                Error: {error}
              </div>
            )}

            {loading ? (
              <div className="flex items-center justify-center h-full">
                <RefreshCw className="w-6 h-6 text-gray-500 animate-spin" />
              </div>
            ) : (
              <div className="space-y-4">
                
                {/* ASSESSMENTS TAB */}
                {activeTab === "assessments" && assessments.length === 0 && (
                  <div className="text-center text-gray-500 py-10 font-mono text-sm">No assessments found.</div>
                )}
                {activeTab === "assessments" && assessments.map((run: any) => (
                  <div key={run.assessment_id} className="p-4 border border-white/10 rounded-lg bg-black/40">
                    <div className="flex justify-between items-start mb-4">
                      <div>
                        <h3 className="text-sm font-bold text-white font-mono">{run.assessment_id}</h3>
                        <p className="text-xs text-gray-400 mt-1">Score: {(run.overall_score * 100).toFixed(1)}% | Evaluated: {run.entities_evaluated} entities</p>
                      </div>
                      <div className="text-right">
                        <p className="text-[10px] text-gray-500 font-mono">{run.start_time}</p>
                        <p className="text-[10px] text-gray-500 font-mono mt-1">{run.execution_duration_ms} ms</p>
                      </div>
                    </div>
                    
                    <div className="grid grid-cols-2 gap-4">
                      <div className="p-3 bg-black/60 rounded border border-white/5">
                        <h4 className="text-xs text-gray-400 font-mono uppercase mb-2">By Status</h4>
                        <div className="space-y-1 text-xs font-mono">
                          {Object.entries(run.counts_by_status || {}).map(([status, count]: [string, any]) => (
                            <div key={status} className="flex justify-between">
                              <span className={status === "FAIL" ? "text-red-400" : status === "WARN" ? "text-amber-400" : status === "UNKNOWN" ? "text-purple-400" : "text-emerald-400"}>{status}</span>
                              <span className="text-white">{count}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                      <div className="p-3 bg-black/60 rounded border border-white/5">
                        <h4 className="text-xs text-gray-400 font-mono uppercase mb-2">By Dimension</h4>
                        <div className="space-y-1 text-[10px] font-mono grid grid-cols-2 gap-x-4">
                          {Object.entries(run.counts_by_dimension || {}).map(([dim, count]: [string, any]) => (
                            <div key={dim} className="flex justify-between">
                              <span className="text-gray-400">{dim}</span>
                              <span className="text-white">{count}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}

                {/* ISSUES TAB */}
                {activeTab === "issues" && issues.length === 0 && (
                  <div className="text-center text-gray-500 py-10 font-mono text-sm">No quality issues found.</div>
                )}
                {activeTab === "issues" && issues.map((issue: any) => (
                  <div key={issue.issue_id} className="p-3 border border-white/10 rounded bg-black/40 flex items-start gap-3">
                    {issue.severity === "CRITICAL" || issue.status === "FAIL" ? (
                      <AlertOctagon className="w-5 h-5 text-red-500 mt-0.5" />
                    ) : (
                      <AlertTriangle className="w-5 h-5 text-amber-500 mt-0.5" />
                    )}
                    <div className="flex-1">
                      <div className="flex justify-between">
                        <h4 className="text-xs font-bold text-white font-mono">{issue.dimension} | {issue.rule_id}</h4>
                        <span className={`text-[9px] font-mono uppercase px-1.5 py-0.5 rounded ${
                          issue.severity === "CRITICAL" ? "bg-red-500/20 text-red-400 border border-red-500/30" : "bg-amber-500/20 text-amber-400 border border-amber-500/30"
                        }`}>
                          {issue.severity}
                        </span>
                      </div>
                      <p className="text-xs text-gray-400 mt-1">{issue.evidence}</p>
                      <div className="flex gap-4 mt-2 text-[10px] text-gray-500 font-mono">
                        <span>Entity: {issue.entity_id || "N/A"}</span>
                        <span>Source: {issue.source}</span>
                      </div>
                    </div>
                  </div>
                ))}

                {/* RULES TAB */}
                {activeTab === "rules" && rules.length === 0 && (
                  <div className="text-center text-gray-500 py-10 font-mono text-sm">No rules defined.</div>
                )}
                {activeTab === "rules" && (
                  <div className="grid grid-cols-2 gap-3">
                    {rules.map((rule: any) => (
                      <div key={rule.rule_id} className="p-3 border border-white/10 rounded bg-black/40">
                        <h4 className="text-xs font-bold text-white font-mono flex justify-between">
                          {rule.name}
                          <span className="text-[9px] bg-white/10 px-1.5 py-0.5 rounded text-gray-400">{rule.dimension}</span>
                        </h4>
                        <p className="text-[10px] text-gray-400 mt-1 h-8">{rule.description}</p>
                      </div>
                    ))}
                  </div>
                )}

              </div>
            )}
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
