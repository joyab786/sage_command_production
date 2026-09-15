"use client";
import React, { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Layers, ShieldCheck, Clock, AlertTriangle, RefreshCw, X, CheckCircle, FileText, Play, RotateCcw } from "lucide-react";

interface TransactionItem {
  transaction_id: string;
  action_id: string;
  status: string;
  data_mode: string;
  expires_at: string;
  created_at: string;
  rollback_supported: string;
  plan: {
    transaction_plan_id: string;
    action_type: string;
    risk_level: string;
    affected_resources: Array<{
      resource_type: string;
      resource_id: string;
      plant_id?: string;
    }>;
    preconditions: Array<{
      field: string;
      operator: string;
      expected_value: any;
      is_satisfied: boolean;
    }>;
    rollback_plan: {
      strategy: string;
      capability: string;
      risk_level: string;
    };
    transaction_plan_hash?: string;
  };
}

interface TransactionPlanModalProps {
  isOpen: boolean;
  onClose: () => void;
  token?: string;
}

export default function TransactionPlanModal({
  isOpen,
  onClose,
  token = "manager_token",
}: TransactionPlanModalProps) {
  const [transactions, setTransactions] = useState<TransactionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedTx, setSelectedTx] = useState<TransactionItem | null>(null);
  const [isExecuting, setIsExecuting] = useState(false);
  const [isRollingBack, setIsRollingBack] = useState(false);
  const [executionMessage, setExecutionMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const fetchTransactions = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("http://localhost:8000/api/v3/transactions?limit=15", {
        headers: {
          Authorization: `Bearer ${token}`,
          "X-Tenant-ID": "tenant_default",
        },
      });
      if (!res.ok) {
        throw new Error(`Failed to load transactions: HTTP ${res.status}`);
      }
      const data = await res.json();
      if (data.success && Array.isArray(data.transactions)) {
        setTransactions(data.transactions);
        if (data.transactions.length > 0 && !selectedTx) {
          setSelectedTx(data.transactions[0]);
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load transactions");
    } finally {
      setLoading(false);
    }
  };

  const handleExecute = async (txId: string) => {
    setIsExecuting(true);
    setExecutionMessage(null);
    try {
      const res = await fetch(`http://localhost:8000/api/v3/transactions/${txId}/execute`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          "X-Tenant-ID": "tenant_default",
        },
        body: JSON.stringify({ transaction_id: txId, dry_run: false }),
      });
      const data = await res.json();
      if (!res.ok) {
        const msg = data.detail?.message || data.error?.message || `Execution failed with HTTP ${res.status}`;
        throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
      }
      setExecutionMessage({
        type: "success",
        text: `Execution Succeeded! ID: ${data.result?.execution_id || "exec_done"} (${data.result?.affected_rows ?? 0} rows affected)`
      });
      fetchTransactions();
    } catch (err: unknown) {
      setExecutionMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Execution failed"
      });
    } finally {
      setIsExecuting(false);
    }
  };

  const handleRollback = async (txId: string) => {
    setIsRollingBack(true);
    setExecutionMessage(null);
    try {
      const res = await fetch(`http://localhost:8000/api/v3/transactions/${txId}/rollback`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          "X-Tenant-ID": "tenant_default",
        },
        body: JSON.stringify({ reason: "Operator requested rollback via UI" }),
      });
      const data = await res.json();
      if (!res.ok) {
        const msg = data.detail?.message || data.error?.message || `Rollback failed with HTTP ${res.status}`;
        throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
      }
      setExecutionMessage({
        type: "success",
        text: `Rollback Completed! Status: ${data.result?.status || "ROLLED_BACK"}`
      });
      fetchTransactions();
    } catch (err: unknown) {
      setExecutionMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Rollback failed"
      });
    } finally {
      setIsRollingBack(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchTransactions();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          transition={{ duration: 0.2 }}
          className="w-full max-w-5xl h-[85vh] bg-[#070707] border border-cyan-500/30 rounded-lg shadow-2xl flex flex-col overflow-hidden text-gray-200"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-[#0c0c0c]">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-cyan-500/10 border border-cyan-500/20 rounded">
                <Layers className="w-5 h-5 text-cyan-400" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="font-mono text-sm font-bold uppercase tracking-wider text-cyan-400">
                    Execution Gateway & Rollback Cortex // V3.0
                  </h2>
                  <span className="px-2 py-0.5 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px] font-mono rounded">
                    GATEWAY ACTIVE
                  </span>
                </div>
                <p className="text-xs text-gray-500 font-mono">
                  Deterministic transaction execution, invariant boundaries, and rollback capabilities
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={fetchTransactions}
                disabled={loading}
                className="p-1.5 hover:bg-white/5 rounded text-gray-400 hover:text-cyan-400 transition-colors"
                title="Refresh transactions"
              >
                <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
              </button>
              <button
                type="button"
                onClick={onClose}
                className="p-1.5 hover:bg-white/5 rounded text-gray-400 hover:text-white transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          {/* Safety Notice Banner */}
          <div className="bg-cyan-950/20 border-b border-cyan-500/20 px-6 py-2 flex items-center justify-between text-[11px] font-mono text-cyan-400/90">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-cyan-400 shrink-0" />
              <span>
                Execution Boundary: Multi-gate server-authoritative validation active. Zero unparameterized SQL writes.
              </span>
            </div>
            <span className="text-[10px] text-cyan-400/80 uppercase">GATEWAY ENFORCED</span>
          </div>

          {/* Body */}
          <div className="flex-1 grid grid-cols-12 overflow-hidden">
            {/* Left: Transaction List */}
            <div className="col-span-5 border-r border-white/10 flex flex-col overflow-hidden bg-black/40">
              <div className="p-3 border-b border-white/5 text-[10px] font-mono text-gray-400 uppercase tracking-wider flex justify-between">
                <span>Planned Transactions</span>
                <span>{transactions.length} Total</span>
              </div>
              <div className="flex-1 overflow-y-auto divide-y divide-white/5 p-2 space-y-1">
                {loading && transactions.length === 0 ? (
                  <div className="p-8 text-center text-xs font-mono text-gray-500 animate-pulse">
                    Querying transaction repository...
                  </div>
                ) : transactions.length === 0 ? (
                  <div className="p-8 text-center text-xs font-mono text-gray-500">
                    No transactions planned yet. Propose an Action to generate a transaction plan.
                  </div>
                ) : (
                  transactions.map((tx) => (
                    <button
                      type="button"
                      key={tx.transaction_id}
                      onClick={() => setSelectedTx(tx)}
                      className={`w-full text-left p-3 rounded transition-colors flex flex-col gap-1.5 font-mono ${
                        selectedTx?.transaction_id === tx.transaction_id
                          ? "bg-cyan-950/40 border border-cyan-500/30"
                          : "hover:bg-white/[0.02] border border-transparent"
                      }`}
                    >
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-bold text-cyan-400">{tx.transaction_id}</span>
                        <span
                          className={`text-[9px] px-1.5 py-0.5 rounded border uppercase ${
                            tx.status === "READY"
                              ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                              : tx.status === "AWAITING_EXECUTION"
                              ? "bg-cyan-500/10 text-cyan-400 border-cyan-500/20"
                              : tx.status === "FAILED"
                              ? "bg-red-500/10 text-red-400 border-red-500/20"
                              : "bg-amber-500/10 text-amber-400 border-amber-500/20"
                          }`}
                        >
                          {tx.status}
                        </span>
                      </div>
                      <div className="text-[11px] text-gray-300">
                        Action: <span className="text-white">{tx.plan.action_type}</span>
                      </div>
                      <div className="flex items-center justify-between text-[10px] text-gray-500">
                        <span>Risk: {tx.plan.risk_level}</span>
                        <span>Mode: {tx.data_mode}</span>
                      </div>
                    </button>
                  ))
                )}
              </div>
            </div>

            {/* Right: Selected Transaction Detail */}
            <div className="col-span-7 flex flex-col overflow-y-auto p-6 space-y-6">
              {selectedTx ? (
                <>
                  {/* Summary Block */}
                  <div className="bg-[#0b0b0b] border border-white/10 rounded p-4 space-y-3 font-mono">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-400 uppercase">Transaction ID</span>
                      <span className="text-sm font-bold text-cyan-400">{selectedTx.transaction_id}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-400 uppercase">Bound Action ID</span>
                      <span className="text-xs text-white">{selectedTx.action_id}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-400 uppercase">Plan Hash (SHA-256)</span>
                      <span className="text-[10px] text-gray-400 truncate max-w-[280px]">
                        {selectedTx.plan.transaction_plan_hash || "Computed on-demand"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-gray-400 uppercase">Expires At</span>
                      <span className="text-amber-400">{selectedTx.expires_at}</span>
                    </div>
                  </div>

                  {/* Affected Resources */}
                  <div className="space-y-2 font-mono">
                    <h3 className="text-xs uppercase tracking-wider text-gray-400">Affected Resources</h3>
                    <div className="grid grid-cols-2 gap-2">
                      {selectedTx.plan.affected_resources.map((res, i) => (
                        <div key={i} className="p-2.5 bg-black/40 border border-white/5 rounded text-xs">
                          <div className="text-[10px] text-gray-500 uppercase">{res.resource_type}</div>
                          <div className="text-cyan-400 font-bold">{res.resource_id}</div>
                          {res.plant_id && <div className="text-[10px] text-gray-400">Plant: {res.plant_id}</div>}
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Preconditions */}
                  <div className="space-y-2 font-mono">
                    <h3 className="text-xs uppercase tracking-wider text-gray-400">Deterministic Preconditions</h3>
                    <div className="space-y-1.5">
                      {selectedTx.plan.preconditions.map((prec, i) => (
                        <div key={i} className="p-2.5 bg-black/40 border border-white/5 rounded flex items-center justify-between text-xs">
                          <div className="flex items-center gap-2">
                            {prec.is_satisfied ? (
                              <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                            ) : (
                              <AlertTriangle className="w-3.5 h-3.5 text-red-400" />
                            )}
                            <span className="text-gray-300">{prec.field} {prec.operator} {String(prec.expected_value)}</span>
                          </div>
                          <span className={`text-[10px] ${prec.is_satisfied ? "text-emerald-400" : "text-red-400"}`}>
                            {prec.is_satisfied ? "SATISFIED" : "FAILED"}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Rollback Plan */}
                  <div className="space-y-2 font-mono">
                    <h3 className="text-xs uppercase tracking-wider text-gray-400">Rollback Capability & Strategy</h3>
                    <div className="p-4 bg-purple-950/20 border border-purple-500/30 rounded space-y-2 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="text-gray-400">Strategy</span>
                        <span className="text-purple-300 font-bold">{selectedTx.plan.rollback_plan.strategy}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-gray-400">Capability</span>
                        <span className="text-purple-300">{selectedTx.plan.rollback_plan.capability}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-gray-400">Rollback Risk</span>
                        <span className="text-purple-300">{selectedTx.plan.rollback_plan.risk_level}</span>
                      </div>
                    </div>
                  </div>

                  {/* Execution Message Banner */}
                  {executionMessage && (
                    <div
                      className={`p-3 rounded border font-mono text-xs flex items-center gap-2 ${
                        executionMessage.type === "success"
                          ? "bg-emerald-950/30 border-emerald-500/30 text-emerald-400"
                          : "bg-red-950/30 border-red-500/30 text-red-400"
                      }`}
                    >
                      {executionMessage.type === "success" ? (
                        <CheckCircle className="w-4 h-4 shrink-0" />
                      ) : (
                        <AlertTriangle className="w-4 h-4 shrink-0" />
                      )}
                      <span>{executionMessage.text}</span>
                    </div>
                  )}

                  {/* Execution Gateway Actions */}
                  <div className="pt-2 border-t border-white/10 flex items-center gap-3 font-mono">
                    <button
                      type="button"
                      disabled={isExecuting || isRollingBack || selectedTx.status === "COMMITTED" || selectedTx.status === "EXECUTING"}
                      onClick={() => handleExecute(selectedTx.transaction_id)}
                      className="flex-1 py-2 px-4 bg-cyan-600 hover:bg-cyan-500 disabled:bg-gray-800 disabled:text-gray-500 text-black font-bold rounded transition-colors text-xs flex items-center justify-center gap-2"
                    >
                      <Play className={`w-3.5 h-3.5 ${isExecuting ? "animate-spin" : ""}`} />
                      <span>{isExecuting ? "Executing Plan..." : "Execute Plan via Gateway"}</span>
                    </button>

                    {(selectedTx.status === "COMMITTED" || selectedTx.status === "FAILED") && (
                      <button
                        type="button"
                        disabled={isRollingBack || isExecuting}
                        onClick={() => handleRollback(selectedTx.transaction_id)}
                        className="py-2 px-4 bg-purple-600/20 hover:bg-purple-600/30 border border-purple-500/40 text-purple-300 font-bold rounded transition-colors text-xs flex items-center gap-2"
                      >
                        <RotateCcw className={`w-3.5 h-3.5 ${isRollingBack ? "animate-spin" : ""}`} />
                        <span>{isRollingBack ? "Rolling back..." : "Rollback Plan"}</span>
                      </button>
                    )}
                  </div>
                </>
              ) : (
                <div className="flex-1 flex items-center justify-center text-xs font-mono text-gray-600">
                  Select a transaction plan from the left panel to inspect details
                </div>
              )}
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
