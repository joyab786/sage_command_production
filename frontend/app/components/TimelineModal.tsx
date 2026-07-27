"use client";
import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Terminal } from "lucide-react";

interface CheckpointItem {
  checkpoint_id: string;
  next?: string[];
  created_at?: string;
  step?: number;
}

interface TimelineModalProps {
  show: boolean;
  history: CheckpointItem[];
  onClose: () => void;
  onRollback: (checkpointId: string) => void;
}

const listItem = {
  hidden: { opacity: 0, x: -15 },
  show: (i: number) => ({
    opacity: 1,
    x: 0,
    transition: { delay: i * 0.05, type: "spring" as const, stiffness: 300, damping: 25 },
  }),
};

export default function TimelineModal({
  show,
  history,
  onClose,
  onRollback,
}: TimelineModalProps) {
  return (
    <AnimatePresence>
      {show && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
        >
          <motion.div
            initial={{ scale: 0.9, y: 30 }}
            animate={{ scale: 1, y: 0 }}
            exit={{ scale: 0.9, y: 30 }}
            transition={{ type: "spring", stiffness: 350, damping: 30 }}
            className="w-[600px] max-h-[80vh] bg-[#050505] border border-cyan-500/20 rounded-2xl shadow-[0_0_60px_rgba(6,182,212,0.15)] overflow-hidden flex flex-col font-mono"
          >
            {/* Header */}
            <div className="p-5 border-b border-white/5 flex justify-between items-center bg-zinc-950">
              <div className="flex items-center gap-2">
                <Terminal className="w-4 h-4 text-cyan-400" />
                <h3 className="text-sm font-bold uppercase tracking-widest text-cyan-400">
                  Timeline Reversion Cortex
                </h3>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="text-gray-500 hover:text-white transition-colors"
              >
                ✕
              </button>
            </div>

            {/* Content */}
            <div className="p-6 overflow-y-auto flex-1 flex flex-col gap-3 scrollbar-hide">
              <p className="text-xs text-gray-400 mb-2">
                Inspect graph state history snapshots. Select a checkpoint to
                fork or undo agent executions.
              </p>

              {history.length === 0 ? (
                <div className="text-center py-8 text-gray-600 text-xs">
                  No checkpoint history recorded for this thread. Run a scan or
                  copilot query first.
                </div>
              ) : (
                history.map((item, idx) => (
                  <motion.div
                    key={idx}
                    custom={idx}
                    variants={listItem}
                    initial="hidden"
                    animate="show"
                    className="p-3.5 bg-black/60 border border-white/5 rounded-lg flex items-center justify-between hover:border-cyan-500/30 transition-colors"
                  >
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center gap-2">
                        <span className="text-cyan-400 text-xs font-bold">
                          #{item.step ?? idx}
                        </span>
                        <span className="text-gray-300 text-xs">
                          {item.checkpoint_id.slice(0, 16)}...
                        </span>
                      </div>
                      <div className="text-[10px] text-gray-500 flex items-center gap-3">
                        <span>
                          Next Node:{" "}
                          {item.next?.length ? item.next.join(", ") : "END"}
                        </span>
                        {item.created_at && (
                          <span>
                            {new Date(item.created_at).toLocaleTimeString()}
                          </span>
                        )}
                      </div>
                    </div>
                    <motion.button
                      type="button"
                      onClick={() => onRollback(item.checkpoint_id)}
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                      className="px-3 py-1.5 bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/20 text-[10px] uppercase font-bold rounded transition-colors"
                    >
                      Revert State
                    </motion.button>
                  </motion.div>
                ))
              )}
            </div>

            {/* Footer */}
            <div className="p-4 border-t border-white/5 bg-zinc-950 flex justify-end">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-xs font-mono uppercase text-gray-400 hover:text-white transition-colors"
              >
                Close Timeline
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
