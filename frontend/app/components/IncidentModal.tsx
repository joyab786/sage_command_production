"use client";

import React, { useState, useEffect, useCallback } from "react";
import { format } from "date-fns";
import { 
  AlertTriangle, CheckCircle2, UserCheck, Plus, RefreshCw, 
  X, Clock, ShieldAlert, FileText, Link2, Paperclip, Send, AlertCircle
} from "lucide-react";
import { fetchSage } from "../../lib/api";

const VALID_TRANSITIONS: Record<string, string[]> = {
  OPEN: ["ACKNOWLEDGED", "CLOSED", "CANCELLED"],
  ACKNOWLEDGED: ["INVESTIGATING", "MITIGATED", "RESOLVED", "CLOSED"],
  INVESTIGATING: ["MITIGATED", "RESOLVED", "CLOSED"],
  MITIGATED: ["RESOLVED", "INVESTIGATING", "CLOSED"],
  RESOLVED: ["CLOSED", "REOPENED"],
  CLOSED: ["REOPENED"],
  REOPENED: ["ACKNOWLEDGED", "INVESTIGATING", "CLOSED"],
  CANCELLED: []
};

const CATEGORIES = [
  "OPERATIONAL", "SAFETY", "QUALITY", "MAINTENANCE", "PRODUCTION",
  "INVENTORY", "SECURITY", "INFRASTRUCTURE", "SYSTEM", "OTHER"
];

const SEVERITIES = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"];
const PRIORITIES = ["LOW", "NORMAL", "HIGH", "URGENT"];
const EVENT_RELATIONSHIPS = ["TRIGGER", "SUPPORTING", "RELATED", "FOLLOW_UP", "RESOLUTION"];
const EVIDENCE_TYPES = [
  "EVENT", "ANOMALY", "TWIN_STATE", "KNOWLEDGE_GRAPH", 
  "DATA_QUALITY", "OPERATOR_NOTE", "EXTERNAL_REFERENCE"
];

export function IncidentModal({ onClose }: { onClose: () => void }) {
  const [incidents, setIncidents] = useState<any[]>([]);
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(null);
  const [incidentDetails, setIncidentDetails] = useState<any>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionMessage, setActionMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Active sub-tab
  const [activeTab, setActiveTab] = useState<"details" | "events" | "evidence" | "notes" | "timeline">("details");

  // Create Incident Modal state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createForm, setCreateForm] = useState({
    title: "",
    description: "",
    category: "OPERATIONAL",
    severity: "LOW",
    priority: "NORMAL"
  });

  // Action input states
  const [transitionState, setTransitionState] = useState("");
  const [transitionReason, setTransitionReason] = useState("");
  const [assignUser, setAssignUser] = useState("");
  const [assignTeam, setAssignTeam] = useState("");
  const [editSeverity, setEditSeverity] = useState("");
  const [editPriority, setEditPriority] = useState("");
  const [newNoteText, setNewNoteText] = useState("");
  const [eventInputId, setEventInputId] = useState("");
  const [eventRelationship, setEventRelationship] = useState("RELATED");
  const [evidenceType, setEvidenceType] = useState("EVENT");
  const [evidenceSourceId, setEvidenceSourceId] = useState("");
  const [evidenceMetaJson, setEvidenceMetaJson] = useState("");

  const loadIncidents = useCallback(async (selectId?: string) => {
    setLoadingList(true);
    try {
      const res = await fetchSage("/api/v3/incidents");
      setIncidents(res);
      if (selectId) {
        setSelectedIncidentId(selectId);
      } else if (res.length > 0 && !selectedIncidentId) {
        setSelectedIncidentId(res[0].incident_id);
      }
    } catch (err: any) {
      setActionMessage({ type: "error", text: `Failed to load incidents: ${err.message}` });
    } finally {
      setLoadingList(false);
    }
  }, [selectedIncidentId]);

  const loadIncidentDetails = useCallback(async (id: string) => {
    setLoadingDetails(true);
    setActionMessage(null);
    try {
      const details = await fetchSage(`/api/v3/incidents/${id}`);
      setIncidentDetails(details);
      const inc = details.incident;
      setAssignUser(inc.assigned_user || "");
      setAssignTeam(inc.assigned_team || "");
      setEditSeverity(inc.severity);
      setEditPriority(inc.priority);
      const nextStates = VALID_TRANSITIONS[inc.status] || [];
      setTransitionState(nextStates.length > 0 ? nextStates[0] : "");
      setTransitionReason("");
    } catch (err: any) {
      setActionMessage({ type: "error", text: `Failed to load details: ${err.message}` });
    } finally {
      setLoadingDetails(false);
    }
  }, []);

  useEffect(() => {
    loadIncidents();
    const interval = setInterval(() => loadIncidents(), 15000);
    return () => clearInterval(interval);
  }, [loadIncidents]);

  useEffect(() => {
    if (selectedIncidentId) {
      loadIncidentDetails(selectedIncidentId);
    }
  }, [selectedIncidentId, loadIncidentDetails]);

  // Operations
  const handleAcknowledge = async () => {
    if (!selectedIncidentId) return;
    setActionLoading(true);
    setActionMessage(null);
    try {
      await fetchSage(`/api/v3/incidents/${selectedIncidentId}/acknowledge`, {
        method: "POST",
        body: JSON.stringify({ reason: "Acknowledged via Command Center" })
      });
      setActionMessage({ type: "success", text: "Incident successfully acknowledged." });
      await loadIncidentDetails(selectedIncidentId);
      await loadIncidents(selectedIncidentId);
    } catch (err: any) {
      setActionMessage({ type: "error", text: `Acknowledgement failed: ${err.message}` });
    } finally {
      setActionLoading(false);
    }
  };

  const handleTransition = async () => {
    if (!selectedIncidentId || !transitionState) return;
    setActionLoading(true);
    setActionMessage(null);
    try {
      await fetchSage(`/api/v3/incidents/${selectedIncidentId}/lifecycle`, {
        method: "PATCH",
        body: JSON.stringify({
          new_state: transitionState,
          reason: transitionReason || `Transitioned to ${transitionState}`,
          expected_version: incidentDetails?.incident?.version
        })
      });
      setActionMessage({ type: "success", text: `Lifecycle advanced to ${transitionState}.` });
      await loadIncidentDetails(selectedIncidentId);
      await loadIncidents(selectedIncidentId);
    } catch (err: any) {
      setActionMessage({ type: "error", text: `Lifecycle transition failed: ${err.message}` });
    } finally {
      setActionLoading(false);
    }
  };

  const handleUpdateAssignment = async () => {
    if (!selectedIncidentId) return;
    setActionLoading(true);
    setActionMessage(null);
    try {
      await fetchSage(`/api/v3/incidents/${selectedIncidentId}/assignment`, {
        method: "PATCH",
        body: JSON.stringify({
          assigned_user: assignUser || null,
          assigned_team: assignTeam || null
        })
      });
      setActionMessage({ type: "success", text: "Incident ownership updated." });
      await loadIncidentDetails(selectedIncidentId);
      await loadIncidents(selectedIncidentId);
    } catch (err: any) {
      setActionMessage({ type: "error", text: `Assignment failed: ${err.message}` });
    } finally {
      setActionLoading(false);
    }
  };

  const handleUpdateAssessment = async () => {
    if (!selectedIncidentId) return;
    setActionLoading(true);
    setActionMessage(null);
    try {
      await fetchSage(`/api/v3/incidents/${selectedIncidentId}/metadata`, {
        method: "PATCH",
        body: JSON.stringify({
          severity: editSeverity,
          priority: editPriority
        })
      });
      setActionMessage({ type: "success", text: "Severity & priority assessment updated." });
      await loadIncidentDetails(selectedIncidentId);
      await loadIncidents(selectedIncidentId);
    } catch (err: any) {
      setActionMessage({ type: "error", text: `Update failed: ${err.message}` });
    } finally {
      setActionLoading(false);
    }
  };

  const handleAddNote = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedIncidentId || !newNoteText.trim()) return;
    setActionLoading(true);
    setActionMessage(null);
    try {
      await fetchSage(`/api/v3/incidents/${selectedIncidentId}/notes`, {
        method: "POST",
        body: JSON.stringify({ text: newNoteText.trim() })
      });
      setNewNoteText("");
      setActionMessage({ type: "success", text: "Operator note recorded." });
      await loadIncidentDetails(selectedIncidentId);
    } catch (err: any) {
      setActionMessage({ type: "error", text: `Note submission failed: ${err.message}` });
    } finally {
      setActionLoading(false);
    }
  };

  const handleAssociateEvent = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedIncidentId || !eventInputId.trim()) return;
    setActionLoading(true);
    setActionMessage(null);
    try {
      await fetchSage(`/api/v3/incidents/${selectedIncidentId}/events`, {
        method: "POST",
        body: JSON.stringify({
          event_id: eventInputId.trim(),
          relationship: eventRelationship
        })
      });
      setEventInputId("");
      setActionMessage({ type: "success", text: `Event ${eventInputId} associated.` });
      await loadIncidentDetails(selectedIncidentId);
    } catch (err: any) {
      setActionMessage({ type: "error", text: `Event association failed: ${err.message}` });
    } finally {
      setActionLoading(false);
    }
  };

  const handleAddEvidence = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedIncidentId || !evidenceSourceId.trim()) return;
    setActionLoading(true);
    setActionMessage(null);
    let parsedMeta: any = {};
    if (evidenceMetaJson.trim()) {
      try {
        parsedMeta = JSON.parse(evidenceMetaJson.trim());
      } catch {
        setActionMessage({ type: "error", text: "Metadata must be valid JSON format." });
        setActionLoading(false);
        return;
      }
    }
    try {
      await fetchSage(`/api/v3/incidents/${selectedIncidentId}/evidence`, {
        method: "POST",
        body: JSON.stringify({
          evidence_type: evidenceType,
          source_id: evidenceSourceId.trim(),
          metadata: parsedMeta
        })
      });
      setEvidenceSourceId("");
      setEvidenceMetaJson("");
      setActionMessage({ type: "success", text: "Evidence reference attached." });
      await loadIncidentDetails(selectedIncidentId);
    } catch (err: any) {
      setActionMessage({ type: "error", text: `Evidence submission failed: ${err.message}` });
    } finally {
      setActionLoading(false);
    }
  };

  const handleCreateIncident = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!createForm.title.trim()) return;
    setActionLoading(true);
    try {
      const created = await fetchSage("/api/v3/incidents", {
        method: "POST",
        body: JSON.stringify(createForm)
      });
      setShowCreateModal(false);
      setCreateForm({
        title: "",
        description: "",
        category: "OPERATIONAL",
        severity: "LOW",
        priority: "NORMAL"
      });
      await loadIncidents(created.incident_id);
    } catch (err: any) {
      setActionMessage({ type: "error", text: `Create incident failed: ${err.message}` });
    } finally {
      setActionLoading(false);
    }
  };

  const currentInc = incidentDetails?.incident;
  const validNextStates = currentInc ? (VALID_TRANSITIONS[currentInc.status] || []) : [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl w-full max-w-7xl max-h-[92vh] overflow-hidden flex flex-col text-slate-100 animate-in fade-in zoom-in-95 duration-200">
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/70">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-amber-500/10 border border-amber-500/20 rounded-lg text-amber-400">
              <ShieldAlert className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                Incident Management Center
                <span className="text-xs font-mono uppercase bg-slate-800 text-amber-400 px-2 py-0.5 rounded border border-amber-500/20">
                  Prompt 18 Controlled UI
                </span>
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Authorized operational tracking, lifecycle transitions, event correlation, and evidence logging.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowCreateModal(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white text-xs font-medium rounded-lg shadow-sm transition-all"
            >
              <Plus className="w-4 h-4" />
              New Incident
            </button>
            <button
              onClick={() => {
                loadIncidents(selectedIncidentId || undefined);
                if (selectedIncidentId) loadIncidentDetails(selectedIncidentId);
              }}
              className="p-1.5 text-slate-400 hover:text-white bg-slate-800 rounded-lg transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-4 h-4 ${loadingList ? "animate-spin" : ""}`} />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 text-slate-400 hover:text-white bg-slate-800 rounded-lg transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Security & Execution Isolation Banner */}
        <div className="px-6 py-1.5 bg-slate-950 border-b border-slate-800/80 flex items-center justify-between text-[11px] text-slate-400 font-mono">
          <div className="flex items-center gap-2">
            <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
            <span>Execution Boundary: Strict Read/Triage Isolation</span>
          </div>
          <div className="text-amber-400/90 font-sans text-[11px]">
            Direct physical execution, PLC controls, and automated remediation are disabled in this view.
          </div>
        </div>

        {/* Global Action Message Banner */}
        {actionMessage && (
          <div className={`px-6 py-2 flex items-center justify-between text-xs border-b ${
            actionMessage.type === "success" 
              ? "bg-emerald-950/60 text-emerald-300 border-emerald-800" 
              : "bg-red-950/60 text-red-300 border-red-800"
          }`}>
            <div className="flex items-center gap-2">
              {actionMessage.type === "success" ? <CheckCircle2 className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
              <span>{actionMessage.text}</span>
            </div>
            <button onClick={() => setActionMessage(null)} className="text-xs hover:underline">Dismiss</button>
          </div>
        )}

        {/* Main Content Pane */}
        <div className="flex-1 overflow-hidden flex">
          
          {/* Left: Incident List */}
          <div className="w-80 border-r border-slate-800 bg-slate-950/40 flex flex-col">
            <div className="p-3 border-b border-slate-800 flex justify-between items-center bg-slate-900/40">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">All Incidents</span>
              <span className="px-2 py-0.5 bg-slate-800 text-slate-300 text-xs font-mono rounded-full">{incidents.length}</span>
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-2">
              {incidents.map((inc) => {
                const isSelected = selectedIncidentId === inc.incident_id;
                const isClosed = inc.status === "CLOSED" || inc.status === "CANCELLED";
                const isOpen = inc.status === "OPEN";
                return (
                  <div
                    key={inc.incident_id}
                    onClick={() => setSelectedIncidentId(inc.incident_id)}
                    className={`p-3 rounded-xl cursor-pointer border transition-all ${
                      isSelected
                        ? "border-amber-500 bg-slate-800/90 shadow-md ring-1 ring-amber-500/20"
                        : "border-slate-800/80 bg-slate-900/40 hover:border-slate-700 hover:bg-slate-850"
                    }`}
                  >
                    <div className="flex justify-between items-start mb-1.5">
                      <span className="text-[10px] font-mono text-slate-400 truncate max-w-[130px]">
                        {inc.incident_id}
                      </span>
                      <span className={`px-2 py-0.5 rounded text-[9px] font-bold tracking-wider uppercase ${
                        isClosed ? "bg-slate-800 text-slate-400" :
                        isOpen ? "bg-red-950/80 text-red-300 border border-red-700/50" :
                        "bg-amber-950/80 text-amber-300 border border-amber-700/50"
                      }`}>
                        {inc.status}
                      </span>
                    </div>
                    <h3 className="text-xs font-semibold text-white line-clamp-1 mb-1">{inc.title}</h3>
                    <div className="flex items-center justify-between text-[11px] text-slate-400 pt-1">
                      <span className={`px-1.5 py-0.5 rounded text-[9px] font-medium ${
                        inc.severity === "CRITICAL" ? "bg-red-900/60 text-red-200 border border-red-700/40" :
                        inc.severity === "HIGH" ? "bg-orange-900/60 text-orange-200 border border-orange-700/40" :
                        "bg-slate-800 text-slate-400"
                      }`}>
                        {inc.severity}
                      </span>
                      <span className="text-[10px] font-mono">{inc.category}</span>
                    </div>
                  </div>
                );
              })}
              {incidents.length === 0 && !loadingList && (
                <div className="p-8 text-center text-slate-500 text-xs">
                  No active incidents recorded.
                </div>
              )}
            </div>
          </div>

          {/* Right: Detailed Controlled Workspace */}
          <div className="flex-1 flex flex-col bg-slate-900/60 overflow-hidden">
            {selectedIncidentId && currentInc ? (
              loadingDetails ? (
                <div className="flex-1 flex items-center justify-center text-slate-400 text-sm">
                  <RefreshCw className="w-5 h-5 animate-spin mr-2" />
                  Loading incident record...
                </div>
              ) : (
                <div className="flex-1 flex flex-col overflow-hidden">
                  
                  {/* Top Bar: Incident Header & Quick Actions */}
                  <div className="p-5 border-b border-slate-800 bg-slate-900/90 flex justify-between items-start">
                    <div className="space-y-1 max-w-2xl">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20">
                          {currentInc.incident_id}
                        </span>
                        <span className="text-xs text-slate-400">v{currentInc.version}</span>
                        <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">
                          {currentInc.category}
                        </span>
                      </div>
                      <h1 className="text-lg font-bold text-white">{currentInc.title}</h1>
                      <p className="text-xs text-slate-400 line-clamp-2">{currentInc.description || "No description provided."}</p>
                    </div>

                    {/* Quick Operator Controls: Acknowledge */}
                    <div className="flex flex-col items-end gap-2 shrink-0">
                      {currentInc.status === "OPEN" && (
                        <button
                          onClick={handleAcknowledge}
                          disabled={actionLoading}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold rounded-lg shadow transition-all disabled:opacity-50"
                        >
                          <CheckCircle2 className="w-4 h-4" />
                          Acknowledge Incident
                        </button>
                      )}
                      {currentInc.acknowledged_at && (
                        <div className="text-[11px] text-slate-400 text-right">
                          <span className="text-emerald-400">✓ Acknowledged</span> by <span className="font-mono text-slate-200">{currentInc.acknowledged_by || "system"}</span>
                          <div className="text-[10px] text-slate-500 font-mono">
                            {format(new Date(currentInc.acknowledged_at), "MMM d, HH:mm:ss")}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Sub-Navigation Tabs */}
                  <div className="flex border-b border-slate-800 px-6 bg-slate-950/40 text-xs">
                    <button
                      onClick={() => setActiveTab("details")}
                      className={`py-3 px-4 font-medium border-b-2 transition-colors flex items-center gap-1.5 ${
                        activeTab === "details"
                          ? "border-amber-500 text-amber-400 bg-amber-500/5"
                          : "border-transparent text-slate-400 hover:text-slate-200"
                      }`}
                    >
                      <FileText className="w-3.5 h-3.5" />
                      Overview & Controls
                    </button>
                    <button
                      onClick={() => setActiveTab("events")}
                      className={`py-3 px-4 font-medium border-b-2 transition-colors flex items-center gap-1.5 ${
                        activeTab === "events"
                          ? "border-amber-500 text-amber-400 bg-amber-500/5"
                          : "border-transparent text-slate-400 hover:text-slate-200"
                      }`}
                    >
                      <Link2 className="w-3.5 h-3.5" />
                      Associated Events ({incidentDetails?.events?.length || 0})
                    </button>
                    <button
                      onClick={() => setActiveTab("evidence")}
                      className={`py-3 px-4 font-medium border-b-2 transition-colors flex items-center gap-1.5 ${
                        activeTab === "evidence"
                          ? "border-amber-500 text-amber-400 bg-amber-500/5"
                          : "border-transparent text-slate-400 hover:text-slate-200"
                      }`}
                    >
                      <Paperclip className="w-3.5 h-3.5" />
                      Evidence References ({incidentDetails?.evidence?.length || 0})
                    </button>
                    <button
                      onClick={() => setActiveTab("notes")}
                      className={`py-3 px-4 font-medium border-b-2 transition-colors flex items-center gap-1.5 ${
                        activeTab === "notes"
                          ? "border-amber-500 text-amber-400 bg-amber-500/5"
                          : "border-transparent text-slate-400 hover:text-slate-200"
                      }`}
                    >
                      <Send className="w-3.5 h-3.5" />
                      Operator Notes ({incidentDetails?.notes?.length || 0})
                    </button>
                    <button
                      onClick={() => setActiveTab("timeline")}
                      className={`py-3 px-4 font-medium border-b-2 transition-colors flex items-center gap-1.5 ${
                        activeTab === "timeline"
                          ? "border-amber-500 text-amber-400 bg-amber-500/5"
                          : "border-transparent text-slate-400 hover:text-slate-200"
                      }`}
                    >
                      <Clock className="w-3.5 h-3.5" />
                      Audit Timeline ({incidentDetails?.timeline?.length || 0})
                    </button>
                  </div>

                  {/* Tab Panes */}
                  <div className="flex-1 overflow-y-auto p-6">
                    
                    {/* TAB 1: DETAILS & RECORD CONTROLS */}
                    {activeTab === "details" && (
                      <div className="space-y-6 max-w-5xl">
                        
                        {/* Status Matrix */}
                        <div className="grid grid-cols-4 gap-4">
                          <div className="bg-slate-800/40 p-3.5 rounded-xl border border-slate-700/60">
                            <span className="block text-[10px] uppercase font-bold tracking-wider text-slate-400 mb-1">Status</span>
                            <span className="text-sm font-bold text-amber-400">{currentInc.status}</span>
                          </div>
                          <div className="bg-slate-800/40 p-3.5 rounded-xl border border-slate-700/60">
                            <span className="block text-[10px] uppercase font-bold tracking-wider text-slate-400 mb-1">Severity</span>
                            <span className="text-sm font-bold text-slate-200">{currentInc.severity}</span>
                          </div>
                          <div className="bg-slate-800/40 p-3.5 rounded-xl border border-slate-700/60">
                            <span className="block text-[10px] uppercase font-bold tracking-wider text-slate-400 mb-1">Priority</span>
                            <span className="text-sm font-bold text-slate-200">{currentInc.priority}</span>
                          </div>
                          <div className="bg-slate-800/40 p-3.5 rounded-xl border border-slate-700/60">
                            <span className="block text-[10px] uppercase font-bold tracking-wider text-slate-400 mb-1">Assigned Owner</span>
                            <span className="text-sm font-bold text-blue-300 font-mono">
                              {currentInc.assigned_user || "Unassigned"}
                            </span>
                          </div>
                        </div>

                        {/* Interactive Control Cards */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                          
                          {/* Lifecycle Transition Card */}
                          <div className="bg-slate-850 p-5 rounded-xl border border-slate-700/80 shadow-sm space-y-4">
                            <div className="flex items-center gap-2 text-white font-semibold text-sm">
                              <RefreshCw className="w-4 h-4 text-amber-400" />
                              Lifecycle State Transition
                            </div>
                            <div className="space-y-3">
                              <div>
                                <label className="block text-xs text-slate-400 mb-1">Next Permitted State</label>
                                <select
                                  value={transitionState}
                                  onChange={(e) => setTransitionState(e.target.value)}
                                  disabled={validNextStates.length === 0}
                                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-amber-500"
                                >
                                  {validNextStates.map((s) => (
                                    <option key={s} value={s}>{s}</option>
                                  ))}
                                  {validNextStates.length === 0 && (
                                    <option value="">No transitions available (Terminal State)</option>
                                  )}
                                </select>
                              </div>
                              <div>
                                <label className="block text-xs text-slate-400 mb-1">Transition Reason / Notes</label>
                                <input
                                  type="text"
                                  value={transitionReason}
                                  onChange={(e) => setTransitionReason(e.target.value)}
                                  placeholder="e.g. Workaround verified, line restarted"
                                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-amber-500"
                                />
                              </div>
                              <button
                                onClick={handleTransition}
                                disabled={actionLoading || validNextStates.length === 0}
                                className="w-full py-2 bg-amber-600 hover:bg-amber-500 text-white font-semibold text-xs rounded-lg transition-all disabled:opacity-40"
                              >
                                {actionLoading ? "Transitioning..." : `Advance Lifecycle to ${transitionState || "N/A"}`}
                              </button>
                            </div>
                          </div>

                          {/* Ownership Assignment Card */}
                          <div className="bg-slate-850 p-5 rounded-xl border border-slate-700/80 shadow-sm space-y-4">
                            <div className="flex items-center gap-2 text-white font-semibold text-sm">
                              <UserCheck className="w-4 h-4 text-blue-400" />
                              Ownership & Assignment
                            </div>
                            <div className="space-y-3">
                              <div>
                                <label className="block text-xs text-slate-400 mb-1">Assigned User ID</label>
                                <input
                                  type="text"
                                  value={assignUser}
                                  onChange={(e) => setAssignUser(e.target.value)}
                                  placeholder="e.g. operator_01, lead_tech"
                                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500"
                                />
                              </div>
                              <div>
                                <label className="block text-xs text-slate-400 mb-1">Assigned Team / Group</label>
                                <input
                                  type="text"
                                  value={assignTeam}
                                  onChange={(e) => setAssignTeam(e.target.value)}
                                  placeholder="e.g. maintenance_tier2, electrical"
                                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500"
                                />
                              </div>
                              <button
                                onClick={handleUpdateAssignment}
                                disabled={actionLoading}
                                className="w-full py-2 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-xs rounded-lg transition-all disabled:opacity-40"
                              >
                                Update Assignment
                              </button>
                            </div>
                          </div>

                          {/* Severity & Priority Adjustment Card */}
                          <div className="bg-slate-850 p-5 rounded-xl border border-slate-700/80 shadow-sm space-y-4">
                            <div className="flex items-center gap-2 text-white font-semibold text-sm">
                              <AlertTriangle className="w-4 h-4 text-orange-400" />
                              Operational Assessment
                            </div>
                            <div className="grid grid-cols-2 gap-3">
                              <div>
                                <label className="block text-xs text-slate-400 mb-1">Severity (Impact)</label>
                                <select
                                  value={editSeverity}
                                  onChange={(e) => setEditSeverity(e.target.value)}
                                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-orange-500"
                                >
                                  {SEVERITIES.map((s) => (
                                    <option key={s} value={s}>{s}</option>
                                  ))}
                                </select>
                              </div>
                              <div>
                                <label className="block text-xs text-slate-400 mb-1">Priority (Attention)</label>
                                <select
                                  value={editPriority}
                                  onChange={(e) => setEditPriority(e.target.value)}
                                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-orange-500"
                                >
                                  {PRIORITIES.map((p) => (
                                    <option key={p} value={p}>{p}</option>
                                  ))}
                                </select>
                              </div>
                            </div>
                            <button
                              onClick={handleUpdateAssessment}
                              disabled={actionLoading}
                              className="w-full py-2 bg-orange-600 hover:bg-orange-500 text-white font-semibold text-xs rounded-lg transition-all disabled:opacity-40"
                            >
                              Update Severity & Priority
                            </button>
                          </div>

                          {/* Scope & Tenant Bounds Card */}
                          <div className="bg-slate-850 p-5 rounded-xl border border-slate-700/80 shadow-sm space-y-3 text-xs">
                            <span className="font-semibold text-white block">Environmental Scope</span>
                            <div className="space-y-1.5 font-mono text-slate-300">
                              <div className="flex justify-between py-1 border-b border-slate-800">
                                <span className="text-slate-500">Tenant ID</span>
                                <span>{currentInc.tenant_id}</span>
                              </div>
                              <div className="flex justify-between py-1 border-b border-slate-800">
                                <span className="text-slate-500">Workspace ID</span>
                                <span>{currentInc.workspace_id || "default"}</span>
                              </div>
                              <div className="flex justify-between py-1 border-b border-slate-800">
                                <span className="text-slate-500">Plant ID</span>
                                <span>{currentInc.plant_id || "plant_01"}</span>
                              </div>
                              <div className="flex justify-between py-1">
                                <span className="text-slate-500">Opened At</span>
                                <span>{format(new Date(currentInc.opened_at), "yyyy-MM-dd HH:mm:ss")}</span>
                              </div>
                            </div>
                          </div>

                        </div>
                      </div>
                    )}

                    {/* TAB 2: ASSOCIATED EVENTS */}
                    {activeTab === "events" && (
                      <div className="space-y-6 max-w-4xl">
                        {/* Event Association Form */}
                        <form onSubmit={handleAssociateEvent} className="bg-slate-850 p-4 rounded-xl border border-slate-700/80 flex gap-3 items-end">
                          <div className="flex-1">
                            <label className="block text-xs text-slate-400 mb-1">Canonical Event ID</label>
                            <input
                              type="text"
                              required
                              value={eventInputId}
                              onChange={(e) => setEventInputId(e.target.value)}
                              placeholder="e.g. evt_9f56752_01"
                              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-amber-500"
                            />
                          </div>
                          <div className="w-48">
                            <label className="block text-xs text-slate-400 mb-1">Relationship</label>
                            <select
                              value={eventRelationship}
                              onChange={(e) => setEventRelationship(e.target.value)}
                              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-amber-500"
                            >
                              {EVENT_RELATIONSHIPS.map((r) => (
                                <option key={r} value={r}>{r}</option>
                              ))}
                            </select>
                          </div>
                          <button
                            type="submit"
                            disabled={actionLoading}
                            className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white font-semibold text-xs rounded-lg transition-all"
                          >
                            Associate Event
                          </button>
                        </form>

                        {/* Associated Events List */}
                        <div className="space-y-2">
                          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Associated Canonical Events</h3>
                          {incidentDetails?.events?.length === 0 ? (
                            <div className="p-6 text-center text-slate-500 text-xs bg-slate-850/40 rounded-xl border border-slate-800">
                              No canonical events associated with this incident record.
                            </div>
                          ) : (
                            incidentDetails.events.map((evt: any) => (
                              <div key={evt.event_id} className="p-3 bg-slate-850 rounded-xl border border-slate-700 flex justify-between items-center text-xs">
                                <div className="space-y-1">
                                  <div className="flex items-center gap-2">
                                    <span className="font-mono text-white">{evt.event_id}</span>
                                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/10 text-amber-300 border border-amber-500/30">
                                      {evt.relationship_type}
                                    </span>
                                  </div>
                                  <div className="text-[11px] text-slate-500">
                                    Linked by {evt.added_by} on {format(new Date(evt.added_at), "yyyy-MM-dd HH:mm")}
                                  </div>
                                </div>
                              </div>
                            ))
                          )}
                        </div>
                      </div>
                    )}

                    {/* TAB 3: EVIDENCE REFERENCES */}
                    {activeTab === "evidence" && (
                      <div className="space-y-6 max-w-4xl">
                        {/* Evidence Input Form */}
                        <form onSubmit={handleAddEvidence} className="bg-slate-850 p-4 rounded-xl border border-slate-700/80 space-y-3">
                          <div className="grid grid-cols-2 gap-3">
                            <div>
                              <label className="block text-xs text-slate-400 mb-1">Evidence Type</label>
                              <select
                                value={evidenceType}
                                onChange={(e) => setEvidenceType(e.target.value)}
                                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-amber-500"
                              >
                                {EVIDENCE_TYPES.map((t) => (
                                  <option key={t} value={t}>{t}</option>
                                ))}
                              </select>
                            </div>
                            <div>
                              <label className="block text-xs text-slate-400 mb-1">Source Reference ID</label>
                              <input
                                type="text"
                                required
                                value={evidenceSourceId}
                                onChange={(e) => setEvidenceSourceId(e.target.value)}
                                placeholder="e.g. anom_87a3b, twin_robot_04"
                                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-amber-500"
                              />
                            </div>
                          </div>
                          <div>
                            <label className="block text-xs text-slate-400 mb-1">Optional Metadata (JSON)</label>
                            <input
                              type="text"
                              value={evidenceMetaJson}
                              onChange={(e) => setEvidenceMetaJson(e.target.value)}
                              placeholder='{"anomaly_score": 0.94, "metric": "temperature"}'
                              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none focus:border-amber-500"
                            />
                          </div>
                          <button
                            type="submit"
                            disabled={actionLoading}
                            className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white font-semibold text-xs rounded-lg transition-all"
                          >
                            Attach Evidence Reference
                          </button>
                        </form>

                        {/* Evidence List */}
                        <div className="space-y-2">
                          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Attached Evidence Records</h3>
                          {incidentDetails?.evidence?.length === 0 ? (
                            <div className="p-6 text-center text-slate-500 text-xs bg-slate-850/40 rounded-xl border border-slate-800">
                              No evidence references attached to this incident.
                            </div>
                          ) : (
                            incidentDetails.evidence.map((evid: any) => (
                              <div key={evid.evidence_id} className="p-3 bg-slate-850 rounded-xl border border-slate-700 space-y-1 text-xs">
                                <div className="flex justify-between items-center">
                                  <span className="font-semibold text-blue-300">{evid.evidence_type}</span>
                                  <span className="text-[10px] text-slate-500 font-mono">
                                    {format(new Date(evid.timestamp), "MMM d, HH:mm:ss")}
                                  </span>
                                </div>
                                <div className="font-mono text-slate-200">Source ID: {evid.source_id}</div>
                                {evid.metadata && Object.keys(evid.metadata).length > 0 && (
                                  <pre className="mt-1 p-2 bg-slate-900 rounded text-[10px] text-slate-400 font-mono overflow-x-auto">
                                    {JSON.stringify(evid.metadata, null, 2)}
                                  </pre>
                                )}
                              </div>
                            ))
                          )}
                        </div>
                      </div>
                    )}

                    {/* TAB 4: OPERATOR NOTES */}
                    {activeTab === "notes" && (
                      <div className="space-y-6 max-w-4xl">
                        {/* Note Input Form */}
                        <form onSubmit={handleAddNote} className="bg-slate-850 p-4 rounded-xl border border-slate-700/80 space-y-3">
                          <div>
                            <div className="flex justify-between items-center mb-1">
                              <label className="text-xs text-slate-400">Add Operator Observation Note</label>
                              <span className="text-[10px] font-mono text-slate-500">{newNoteText.length} / 4096</span>
                            </div>
                            <textarea
                              rows={3}
                              required
                              maxLength={4096}
                              value={newNoteText}
                              onChange={(e) => setNewNoteText(e.target.value)}
                              placeholder="Record observations, shift handoff notes, or mitigation steps taken..."
                              className="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-xs text-white focus:outline-none focus:border-amber-500"
                            />
                          </div>
                          <button
                            type="submit"
                            disabled={actionLoading || !newNoteText.trim()}
                            className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white font-semibold text-xs rounded-lg transition-all disabled:opacity-40"
                          >
                            Submit Operator Note
                          </button>
                        </form>

                        {/* Notes Feed */}
                        <div className="space-y-3">
                          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Historical Notes Ledger</h3>
                          {incidentDetails?.notes?.length === 0 ? (
                            <div className="p-6 text-center text-slate-500 text-xs bg-slate-850/40 rounded-xl border border-slate-800">
                              No notes recorded yet.
                            </div>
                          ) : (
                            incidentDetails.notes.map((note: any) => (
                              <div key={note.note_id} className="p-4 bg-slate-850 rounded-xl border border-slate-700 space-y-2 text-xs">
                                <div className="flex justify-between items-center text-[11px] text-slate-400">
                                  <span className="font-semibold text-amber-400">{note.author}</span>
                                  <span className="font-mono text-slate-500">{format(new Date(note.timestamp), "yyyy-MM-dd HH:mm:ss")}</span>
                                </div>
                                <p className="text-slate-200 whitespace-pre-wrap">{note.text}</p>
                              </div>
                            ))
                          )}
                        </div>
                      </div>
                    )}

                    {/* TAB 5: AUDIT TIMELINE */}
                    {activeTab === "timeline" && (
                      <div className="space-y-4 max-w-4xl">
                        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Deterministic Audit Timeline</h3>
                        {incidentDetails?.timeline?.length === 0 ? (
                          <div className="p-6 text-center text-slate-500 text-xs bg-slate-850/40 rounded-xl border border-slate-800">
                            No timeline entries.
                          </div>
                        ) : (
                          <div className="space-y-3 relative border-l-2 border-slate-700 ml-3 pl-4">
                            {incidentDetails.timeline.map((entry: any) => (
                              <div key={entry.entry_id} className="text-xs space-y-1 relative">
                                <div className="absolute -left-[23px] top-1 w-3 h-3 rounded-full bg-amber-500 border-2 border-slate-900"></div>
                                <div className="flex items-center gap-2">
                                  <span className="font-semibold text-amber-300">{entry.entry_type}</span>
                                  <span className="text-slate-500 text-[11px]">by {entry.actor}</span>
                                  <span className="text-slate-500 font-mono text-[10px] ml-auto">
                                    {format(new Date(entry.timestamp), "MMM d, HH:mm:ss")}
                                  </span>
                                </div>
                                {entry.metadata && Object.keys(entry.metadata).length > 0 && (
                                  <pre className="text-[10px] font-mono bg-slate-900 p-2 rounded text-slate-400 overflow-x-auto">
                                    {JSON.stringify(entry.metadata, null, 2)}
                                  </pre>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                  </div>

                </div>
              )
            ) : (
              <div className="flex-1 flex items-center justify-center text-slate-500 text-xs">
                Select an incident from the left panel to inspect and manage.
              </div>
            )}
          </div>

        </div>

      </div>

      {/* Controlled Create Incident Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 w-full max-w-md shadow-2xl text-slate-100 space-y-4">
            <div className="flex justify-between items-center border-b border-slate-800 pb-3">
              <h3 className="font-bold text-white text-base flex items-center gap-2">
                <Plus className="w-4 h-4 text-amber-500" />
                Create New Incident Record
              </h3>
              <button onClick={() => setShowCreateModal(false)} className="text-slate-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleCreateIncident} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-400 mb-1">Title *</label>
                <input
                  type="text"
                  required
                  value={createForm.title}
                  onChange={(e) => setCreateForm({ ...createForm, title: e.target.value })}
                  placeholder="e.g. Excessive Bearing Vibration on Conveyor 2"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white focus:outline-none focus:border-amber-500"
                />
              </div>
              <div>
                <label className="block text-slate-400 mb-1">Description</label>
                <textarea
                  rows={2}
                  value={createForm.description}
                  onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })}
                  placeholder="Operational context and initial observations..."
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white focus:outline-none focus:border-amber-500"
                />
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="block text-slate-400 mb-1">Category</label>
                  <select
                    value={createForm.category}
                    onChange={(e) => setCreateForm({ ...createForm, category: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-white"
                  >
                    {CATEGORIES.map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Severity</label>
                  <select
                    value={createForm.severity}
                    onChange={(e) => setCreateForm({ ...createForm, severity: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-white"
                  >
                    {SEVERITIES.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Priority</label>
                  <select
                    value={createForm.priority}
                    onChange={(e) => setCreateForm({ ...createForm, priority: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-white"
                  >
                    {PRIORITIES.map((p) => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="pt-2 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="px-3 py-2 bg-slate-800 text-slate-300 rounded-lg hover:bg-slate-700"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white font-bold rounded-lg disabled:opacity-50"
                >
                  Create Incident
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}
