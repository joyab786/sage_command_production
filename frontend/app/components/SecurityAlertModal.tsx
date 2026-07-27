"use client";
import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ShieldAlert } from "lucide-react";

interface SecurityAlertModalProps {
  alert: { threat_level: string; details: string } | null;
  onDismiss: () => void;
}

export default function SecurityAlertModal({
  alert,
  onDismiss,
}: SecurityAlertModalProps) {
  return (
    <AnimatePresence>
      {alert && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[60] flex items-center justify-center bg-red-950/80 backdrop-blur-md"
        >
          {/* Red scan line */}
          <div className="scan-line" />

          <motion.div
            initial={{ scale: 0.85, y: 30 }}
            animate={{ scale: 1, y: 0 }}
            exit={{ scale: 0.85, y: 30 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
            className="w-[550px] bg-[#080202] border-2 border-red-500 rounded-2xl shadow-[0_0_80px_rgba(239,68,68,0.4)] overflow-hidden flex flex-col font-mono relative"
          >
            {/* Inner scan line */}
            <div className="scan-line" />

            {/* Header */}
            <div className="p-5 border-b border-red-500/30 flex items-center justify-between bg-red-950/90">
              <div className="flex items-center gap-3">
                <motion.div
                  animate={{ y: [0, -4, 0] }}
                  transition={{ duration: 0.6, repeat: Infinity }}
                >
                  <ShieldAlert className="w-6 h-6 text-red-400" />
                </motion.div>
                <div>
                  <h3 className="text-sm font-bold uppercase tracking-widest text-red-400 glitch-text">
                    DEFCON 1: CYBERSECURITY THREAT INTERCEPTED
                  </h3>
                  <span className="text-[10px] text-red-300/80 uppercase">
                    Intrusion Agent Triggered // System Lockdown
                  </span>
                </div>
              </div>
            </div>

            {/* Content */}
            <div className="p-6 flex flex-col gap-4">
              <motion.div
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.3 }}
                className="bg-black/80 border border-red-500/30 p-4 rounded-lg"
              >
                <span className="text-[10px] text-red-400 uppercase font-bold block mb-1">
                  Threat Analysis &amp; Details:
                </span>
                <p className="text-sm text-red-200 leading-relaxed">
                  {alert.details}
                </p>
              </motion.div>

              <motion.p
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.5 }}
                className="text-xs text-gray-400 leading-relaxed"
              >
                Execution graph has been halted to prevent unauthorized database
                access or prompt injection tampering. Review the raw telemetry
                console logs for details.
              </motion.p>
            </div>

            {/* Footer */}
            <div className="p-4 border-t border-red-500/20 bg-zinc-950 flex justify-end gap-3">
              <motion.button
                type="button"
                onClick={onDismiss}
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                className="px-6 py-2 bg-red-500 text-black font-bold uppercase tracking-widest text-xs rounded hover:bg-red-400 transition-all shadow-[0_0_20px_rgba(239,68,68,0.5)]"
              >
                Acknowledge &amp; Clear Alert
              </motion.button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
