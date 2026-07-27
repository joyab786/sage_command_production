"use client";
import React, { useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ShieldAlert, CheckCircle2, Terminal } from "lucide-react";
import BlastRadiusDisplay from "./BlastRadiusDisplay";

interface ExecutionFeedProps {
  logs: string[];
  guardrailPayload: any;
  blastRadiusData: any;
  visionFinding: any;
  userRole: "operator" | "manager";
  onApprove: () => void;
  onAbort: () => void;
}

export default function ExecutionFeed({
  logs,
  guardrailPayload,
  blastRadiusData,
  visionFinding,
  userRole,
  onApprove,
  onAbort,
}: ExecutionFeedProps) {
  const logsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  return (
    <div className="bg-zinc-950 border border-white/5 rounded-xl flex flex-col overflow-hidden h-full">
      {/* Tab header */}
      <div className="flex items-center border-b border-white/5 bg-[#050505]">
        <div className="flex items-center gap-2 px-4 py-3 text-xs font-mono uppercase tracking-widest text-cyan-400 border-b-2 border-cyan-400 bg-white/[0.02]">
          <Terminal className="w-3 h-3" />
          Execution Feed
        </div>
      </div>

      <div className="flex-1 p-4 font-mono text-xs overflow-y-auto flex flex-col gap-3 scrollbar-hide">
        {/* Boot verification */}
        <motion.div
          initial={{ opacity: 0, x: -10 }}
          animate={{ opacity: 1, x: 0 }}
          className="flex items-start gap-3 p-3 rounded-lg group"
        >
          <CheckCircle2 className="w-4 h-4 text-green-500 mt-0.5 shrink-0" />
          <div>
            <p className="text-gray-300 font-semibold mb-1">Verify Boot Signatures</p>
            <p className="text-gray-500 text-[10px]">
              Neural core and local dependencies authenticated.
            </p>
          </div>
        </motion.div>

        {/* Vision Diagnostics Finding */}
        <AnimatePresence>
          {visionFinding && (
            <motion.div
              initial={{ opacity: 0, scale: 0.97 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.97 }}
              className="p-4 bg-amber-500/[0.03] border border-amber-500/20 rounded-xl shadow-[0_0_30px_rgba(245,158,11,0.05)] font-mono"
            >
              <div className="flex items-center justify-between border-b border-white/5 pb-2 mb-3">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-amber-400">
                    🔬 Vision Diagnostic Assessment
                  </span>
                </div>
                <span
                  className={`text-[9px] font-bold px-2 py-0.5 rounded uppercase border ${
                    visionFinding.severity === "CRITICAL"
                      ? "bg-red-500/20 text-red-400 border-red-500/30"
                      : "bg-amber-500/20 text-amber-400 border-amber-500/30"
                  }`}
                >
                  {visionFinding.severity || "HIGH"} SEVERITY
                </span>
              </div>
              <div className="bg-black/50 p-3 rounded border border-amber-500/10 flex flex-col gap-2">
                <div>
                  <span className="text-[9px] text-gray-500 uppercase block">
                    Part Identified:
                  </span>
                  <span className="text-sm font-bold text-white">
                    {visionFinding.part_identified}
                  </span>
                </div>
                <div>
                  <span className="text-[9px] text-gray-500 uppercase block">
                    Damage Assessment:
                  </span>
                  <span className="text-xs text-gray-300">
                    {visionFinding.damage_assessment}
                  </span>
                </div>
                <div>
                  <span className="text-[9px] text-gray-500 uppercase block">
                    Recommended Action:
                  </span>
                  <span className="text-xs text-amber-400 font-bold">
                    {visionFinding.recommended_action}
                  </span>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Blast Radius */}
        <BlastRadiusDisplay data={blastRadiusData} />

        {/* Guardrail Interrupt */}
        <AnimatePresence>
          {guardrailPayload && (
            <motion.div
              initial={{ opacity: 0, scale: 0.97, y: 10 }}
              animate={{
                opacity: 1,
                scale: 1,
                y: 0,
                borderColor: [
                  "rgba(239,68,68,0.2)",
                  "rgba(239,68,68,0.5)",
                  "rgba(239,68,68,0.2)",
                ],
              }}
              exit={{ opacity: 0, scale: 0.97 }}
              transition={{
                borderColor: { duration: 2, repeat: Infinity },
                default: { type: "spring", stiffness: 300, damping: 25 },
              }}
              className="flex items-start gap-4 p-4 bg-red-500/[0.03] border-2 border-red-500/20 rounded-xl shadow-[0_0_30px_rgba(239,68,68,0.06)] font-mono"
            >
              <motion.div
                animate={{ rotate: [0, -5, 5, 0] }}
                transition={{ duration: 0.5, repeat: 3 }}
              >
                <ShieldAlert className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
              </motion.div>
              <div className="flex-1">
                <div className="flex items-center justify-between">
                  <p className="text-red-400 font-bold uppercase tracking-wider text-sm">
                    Execution Halted (PENDING)
                  </p>
                  {userRole === "operator" && (
                    <span className="px-2 py-0.5 bg-red-950/80 border border-red-500/40 text-red-400 text-[9px] font-bold uppercase tracking-wider rounded">
                      Manager Authorization Required
                    </span>
                  )}
                </div>
                <div className="bg-black/50 p-3 rounded border border-red-500/10 my-3">
                  <p className="text-gray-500 text-[10px] uppercase mb-1">
                    Proposed AI Action:
                  </p>
                  <p className="text-white text-sm mb-2">
                    {">"} {guardrailPayload.action}
                  </p>
                  <p className="text-gray-500 text-[10px] uppercase mb-1">
                    AI Logic Justification:
                  </p>
                  <p className="text-gray-400">{guardrailPayload.justification}</p>
                </div>
                <div className="flex gap-3 mt-4 items-center">
                  <motion.button
                    type="button"
                    onClick={onApprove}
                    disabled={userRole === "operator"}
                    whileHover={
                      userRole !== "operator" ? { scale: 1.05 } : undefined
                    }
                    whileTap={
                      userRole !== "operator" ? { scale: 0.95 } : undefined
                    }
                    className={`px-4 py-2 font-bold uppercase tracking-widest text-[10px] rounded transition-all ${
                      userRole === "operator"
                        ? "bg-zinc-800 text-gray-500 border border-white/5 cursor-not-allowed opacity-60"
                        : "bg-red-500 text-black hover:bg-red-400 shadow-[0_0_15px_rgba(239,68,68,0.4)]"
                    }`}
                  >
                    {userRole === "operator"
                      ? "Locked (Manager Only)"
                      : "Authorize Action"}
                  </motion.button>
                  <motion.button
                    type="button"
                    onClick={onAbort}
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    className="px-4 py-2 border border-white/10 text-gray-400 font-bold uppercase tracking-widest text-[10px] rounded hover:bg-white/5 transition-colors"
                  >
                    Abort Sequence
                  </motion.button>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Raw Console Logs */}
        <div className="mt-auto pt-4 border-t border-white/5">
          <div className="p-3 bg-[#020202] border border-white/5 rounded-lg text-[10px] leading-relaxed text-gray-500 font-mono shadow-inner h-32 overflow-y-auto flex flex-col-reverse scrollbar-hide">
            <div>
              <AnimatePresence initial={false}>
                {logs.map((log, i) => (
                  <motion.p
                    key={i}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.15 }}
                    className={
                      log.includes("[WARN]") || log.includes("[ERROR]")
                        ? "text-red-400"
                        : log.includes("[AGENT]") || log.includes("[SUCCESS]")
                        ? "text-purple-400"
                        : log.includes("[TELEMETRY]")
                        ? "text-cyan-400/70"
                        : "text-gray-400"
                    }
                  >
                    {log}
                  </motion.p>
                ))}
              </AnimatePresence>
              <motion.div
                animate={{ opacity: [1, 0] }}
                transition={{ repeat: Infinity, duration: 0.8 }}
                className="w-2 h-3 bg-gray-500 mt-1 inline-block"
              />
              <div ref={logsEndRef} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
