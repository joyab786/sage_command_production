"use client";
import React from "react";
import { motion, AnimatePresence } from "framer-motion";

interface LiveDbModalProps {
  show: boolean;
  liveDbUri: string;
  isLinking: boolean;
  onClose: () => void;
  onUriChange: (value: string) => void;
  onSubmit: (e: React.FormEvent) => void;
}

export default function LiveDbModal({
  show,
  liveDbUri,
  isLinking,
  onClose,
  onUriChange,
  onSubmit,
}: LiveDbModalProps) {
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
            className="w-[500px] bg-[#050505] border border-white/10 rounded-2xl shadow-[0_0_60px_rgba(0,0,0,0.8)] overflow-hidden"
          >
            <div className="p-5 border-b border-white/5 flex justify-between items-center bg-zinc-950">
              <h3 className="text-sm font-bold uppercase tracking-widest text-purple-400">
                Establish Live Tether
              </h3>
              <button
                type="button"
                onClick={onClose}
                className="text-gray-500 hover:text-white transition-colors"
              >
                ✕
              </button>
            </div>
            <form onSubmit={onSubmit} className="p-6">
              <p className="text-xs text-gray-500 font-mono mb-4">
                Inject a valid connection string (PostgreSQL, MySQL, AWS RDS) to
                route the AI&apos;s visual cortex to a live production cluster.
              </p>
              <input
                type="password"
                value={liveDbUri}
                onChange={(e) => onUriChange(e.target.value)}
                placeholder="postgresql://user:password@localhost:5432/dbname"
                className="w-full bg-[#020202] border border-white/10 rounded py-3 px-4 text-xs font-mono text-white focus:outline-none focus:border-purple-500 transition-colors mb-6"
              />
              <div className="flex justify-end gap-3">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 text-xs font-mono uppercase text-gray-400 hover:text-white"
                >
                  Cancel
                </button>
                <motion.button
                  type="submit"
                  disabled={isLinking || !liveDbUri}
                  whileHover={{ scale: 1.03 }}
                  whileTap={{ scale: 0.97 }}
                  className="px-6 py-2 bg-purple-500 text-black font-bold uppercase tracking-widest text-xs rounded hover:bg-purple-400 disabled:opacity-50 transition-colors shadow-[0_0_15px_rgba(168,85,247,0.3)]"
                >
                  {isLinking ? "Connecting..." : "Initialize Link"}
                </motion.button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
