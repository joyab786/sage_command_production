"use client";
import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Activity } from "lucide-react";

interface AffectedSystem {
  name: string;
  status: string;
  impact_delay: string;
}

interface TimelineEvent {
  timeframe: string;
  impact: string;
}

interface BlastRadiusProps {
  data: {
    urgency_rating?: string;
    financial_exposure?: string;
    summary?: string;
    affected_systems?: AffectedSystem[];
    cascading_timeline?: TimelineEvent[];
  } | null;
}

const statusColors: Record<string, string> = {
  CRITICAL: "bg-red-500/20 text-red-400 border-red-500/30",
  WARNING: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  DEGRADED: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  STABLE: "bg-green-500/20 text-green-400 border-green-500/30",
};

const urgencyColors: Record<string, string> = {
  CRITICAL: "bg-red-500/20 text-red-400 border border-red-500/40",
  HIGH: "bg-amber-500/20 text-amber-400 border border-amber-500/40",
  MEDIUM: "bg-yellow-500/20 text-yellow-400 border border-yellow-500/40",
  LOW: "bg-green-500/20 text-green-400 border border-green-500/40",
};

export default function BlastRadiusDisplay({ data }: BlastRadiusProps) {
  if (!data) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 15 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
        className="p-4 bg-zinc-950/80 border border-cyan-500/20 rounded-xl shadow-[0_0_30px_rgba(6,182,212,0.06)] font-mono relative overflow-hidden"
      >
        {/* Top accent line */}
        <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-cyan-500/40 to-transparent" />

        {/* Header */}
        <div className="flex items-center justify-between mb-3 pb-2 border-b border-white/5">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-cyan-400" />
            <span className="text-xs font-bold uppercase tracking-wider text-cyan-400">
              Blast Radius Visual Cortex
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-gray-400 uppercase">Exposure:</span>
            <motion.span
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: 0.3 }}
              className="text-xs font-bold text-green-400 bg-green-500/10 px-2 py-0.5 rounded border border-green-500/20"
            >
              {data.financial_exposure || "$28,500 USD"}
            </motion.span>
            <span
              className={`text-[10px] font-bold px-2 py-0.5 rounded uppercase ${
                urgencyColors[data.urgency_rating || "HIGH"]
              }`}
            >
              {data.urgency_rating || "HIGH"} URGENCY
            </span>
          </div>
        </div>

        {/* Blast Origin Pulse */}
        <div className="relative flex items-center justify-center py-4 mb-4">
          <div className="relative">
            {/* Concentric pulsing rings */}
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="w-16 h-16 rounded-full border border-red-500/30 blast-ring" />
            </div>
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="w-16 h-16 rounded-full border border-amber-500/20 blast-ring blast-ring-delay-1" />
            </div>
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="w-16 h-16 rounded-full border border-cyan-500/10 blast-ring blast-ring-delay-2" />
            </div>
            {/* Core anomaly dot */}
            <motion.div
              animate={{ scale: [1, 1.2, 1] }}
              transition={{ duration: 1.5, repeat: Infinity }}
              className="relative z-10 w-4 h-4 bg-red-500 rounded-full shadow-[0_0_20px_rgba(239,68,68,0.6)] mx-auto"
            />
          </div>
        </div>

        {/* Summary */}
        <p className="text-[11px] text-gray-300 mb-3 leading-relaxed">{data.summary}</p>

        {/* Affected Systems Grid */}
        <div className="grid grid-cols-3 gap-2 mb-4">
          {data.affected_systems?.map((sys, idx) => (
            <motion.div
              key={idx}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 * idx }}
              className="p-2.5 bg-black/60 border border-white/5 rounded-lg flex flex-col justify-between hover:border-white/10 transition-colors"
            >
              <span className="text-[10px] font-bold text-gray-300 truncate">
                {sys.name}
              </span>
              <div className="flex items-center justify-between mt-2">
                <span
                  className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${
                    statusColors[sys.status] || statusColors.WARNING
                  }`}
                >
                  {sys.status}
                </span>
                <span className="text-[9px] text-gray-500">{sys.impact_delay}</span>
              </div>
            </motion.div>
          ))}
        </div>

        {/* Cascading Timeline */}
        <div className="pt-2 border-t border-white/5">
          <span className="text-[10px] uppercase text-gray-500 font-bold mb-2 block">
            Cascading Impact Timeline
          </span>
          <div className="flex flex-col gap-2 relative pl-3 border-l border-cyan-500/30">
            {data.cascading_timeline?.map((evt, idx) => (
              <motion.div
                key={idx}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.15 * idx + 0.3 }}
                className="relative flex items-start gap-2"
              >
                <span className="absolute -left-[17px] top-1.5 w-2 h-2 rounded-full bg-cyan-400 shadow-[0_0_8px_rgba(6,182,212,0.8)]" />
                <span className="text-[10px] font-bold text-cyan-400 shrink-0 w-16">
                  {evt.timeframe}
                </span>
                <span className="text-[10px] text-gray-300 flex-1">{evt.impact}</span>
              </motion.div>
            ))}
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
