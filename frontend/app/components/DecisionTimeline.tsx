"use client";
import React, { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ShieldCheck, History, RefreshCw, Key, Shield, Clock, FileText } from "lucide-react";

interface LedgerEventItem {
  event_id: string;
  event_type: string;
  category: string;
  event_status: string;
  occurred_at: string;
  actor: {
    actor_type: string;
    actor_id: string;
    acting_user_id?: string;
  };
  data_mode: string;
  action_id?: string;
  correlation_id?: string;
  event_hash: string;
  payload?: Record<string, unknown>;
}

interface DecisionTimelineProps {
  isOpen: boolean;
  onClose: () => void;
  token?: string;
}

export default function DecisionTimeline({
  isOpen,
  onClose,
  token = "manager_token",
}: DecisionTimelineProps) {
  const [events, setEvents] = useState<LedgerEventItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTimeline = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("http://localhost:8000/api/v3/audit/events?limit=25", {
        headers: {
          Authorization: `Bearer ${token}`,
          "X-Tenant-ID": "tenant_default",
        },
      });
      if (!res.ok) {
        throw new Error(`Audit query error: HTTP ${res.status}`);
      }
      const data = await res.json();
      if (data.success && Array.isArray(data.events)) {
        setEvents(data.events);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load audit events");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchTimeline();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 10 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 10 }}
          className="relative w-full max-w-4xl max-h-[85vh] bg-[#0A0D14] border border-cyan-500/20 rounded-xl shadow-2xl flex flex-col overflow-hidden text-slate-200"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-cyan-500/20 bg-[#0F1420]/80">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
                <History className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-semibold text-lg text-slate-100 flex items-center gap-2">
                  Audit & Decision Ledger
                  <span className="text-xs px-2 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-800/60 text-cyan-400 font-mono">
                    Append-Only Immutable
                  </span>
                </h3>
                <p className="text-xs text-slate-400">
                  Cryptographically fingerprinted history of system operations & AI decisions
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={fetchTimeline}
                disabled={loading}
                className="p-2 rounded-lg bg-slate-900 border border-slate-700 hover:border-cyan-500/50 text-slate-300 hover:text-cyan-400 transition-colors"
                title="Refresh Ledger"
              >
                <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
              </button>
              <button
                onClick={onClose}
                className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700 hover:border-slate-500 text-xs text-slate-300 transition-colors"
              >
                Close
              </button>
            </div>
          </div>

          {/* Event Stream Body */}
          <div className="flex-1 overflow-y-auto p-6 space-y-4 font-sans">
            {error && (
              <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800 text-xs text-rose-300">
                {error}
              </div>
            )}

            {events.length === 0 && !loading && !error && (
              <div className="text-center py-12 text-slate-500 text-sm">
                No audit events recorded in this partition yet.
              </div>
            )}

            {events.map((evt) => {
              const isAllow = evt.event_type.includes("ALLOWED") || evt.event_type.includes("SUCCESS");
              const isDeny = evt.event_type.includes("DENIED") || evt.event_type.includes("FAILED");
              const isSim = evt.data_mode === "SIMULATION";

              return (
                <div
                  key={evt.event_id}
                  className="p-4 rounded-lg bg-[#0E121B]/90 border border-slate-800 hover:border-cyan-500/30 transition-all space-y-2"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span
                        className={`text-xs font-mono font-medium px-2.5 py-0.5 rounded border ${
                          isAllow
                            ? "bg-emerald-950/40 text-emerald-400 border-emerald-800/60"
                            : isDeny
                            ? "bg-rose-950/40 text-rose-400 border-rose-800/60"
                            : "bg-cyan-950/40 text-cyan-400 border-cyan-800/60"
                        }`}
                      >
                        {evt.event_type}
                      </span>
                      {isSim && (
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-950/40 border border-amber-800/60 text-amber-300">
                          SIMULATION
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-slate-500 font-mono flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {evt.occurred_at}
                    </span>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs pt-1 border-t border-slate-800/60">
                    <div>
                      <span className="text-slate-500">Actor:</span>{" "}
                      <span className="text-slate-300 font-mono">
                        {evt.actor.actor_type}:{evt.actor.actor_id}
                      </span>
                    </div>
                    {evt.action_id && (
                      <div>
                        <span className="text-slate-500">Action:</span>{" "}
                        <span className="text-cyan-400 font-mono">{evt.action_id}</span>
                      </div>
                    )}
                    {evt.correlation_id && (
                      <div>
                        <span className="text-slate-500">Correlation:</span>{" "}
                        <span className="text-slate-400 font-mono">{evt.correlation_id}</span>
                      </div>
                    )}
                    <div className="sm:text-right">
                      <span className="text-slate-500">Status:</span>{" "}
                      <span className="text-slate-300 font-semibold">{evt.event_status}</span>
                    </div>
                  </div>

                  {/* Fingerprint footer */}
                  <div className="flex items-center justify-between text-[11px] pt-1 text-slate-500 font-mono">
                    <span className="flex items-center gap-1 text-slate-400 truncate max-w-[70%]">
                      <Key className="w-3 h-3 text-cyan-500 shrink-0" />
                      <span className="truncate">Hash: {evt.event_hash}</span>
                    </span>
                    <span className="text-slate-600">ID: {evt.event_id}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
