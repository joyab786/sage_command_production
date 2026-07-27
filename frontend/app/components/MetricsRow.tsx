"use client";
import React from "react";
import { motion } from "framer-motion";

interface MetricData {
  label: string;
  value: string;
  unit: string;
  trend: string;
  color: string;
}

interface MetricsRowProps {
  systemStatus: string;
  guardrailPayload: any;
}

const container = {
  hidden: {},
  show: {
    transition: { staggerChildren: 0.1 },
  },
};

const cardVariant = {
  hidden: { opacity: 0, y: 20, scale: 0.95 },
  show: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { type: "spring" as const, stiffness: 300, damping: 24 },
  },
};

export default function MetricsRow({ systemStatus, guardrailPayload }: MetricsRowProps) {
  const metrics: MetricData[] = [
    {
      label: "System Status",
      value: systemStatus,
      unit: "",
      trend: "Live",
      color:
        systemStatus === "INTERRUPTED"
          ? "text-red-400"
          : systemStatus === "LOCKDOWN"
          ? "text-red-500"
          : systemStatus === "ONLINE"
          ? "text-cyan-400"
          : "text-gray-500",
    },
    {
      label: "AI Confidence Matrix",
      value: "99.8",
      unit: "%",
      trend: "Optimal",
      color: "text-green-400",
    },
    {
      label: "Active Threat Vectors",
      value: guardrailPayload ? "1" : "0",
      unit: "Detected",
      trend: guardrailPayload ? "Action Req" : "Secured",
      color: guardrailPayload ? "text-red-400" : "text-gray-400",
    },
  ];

  return (
    <motion.div
      variants={container}
      initial="hidden"
      animate="show"
      className="grid grid-cols-3 gap-4"
    >
      {metrics.map((metric, i) => (
        <motion.div
          key={i}
          variants={cardVariant}
          whileHover={{ scale: 1.02, borderColor: "rgba(255,255,255,0.12)" }}
          transition={{ type: "spring", stiffness: 400, damping: 25 }}
          className="bg-zinc-950 border border-white/5 rounded-xl p-4 flex flex-col justify-between relative overflow-hidden cursor-default group"
        >
          {/* Subtle corner glow */}
          <div className="absolute top-0 right-0 w-20 h-20 bg-white/[0.008] rounded-full blur-2xl -mr-10 -mt-10 group-hover:bg-white/[0.02] transition-all duration-700" />

          <span className="text-[10px] font-mono uppercase tracking-widest text-gray-500">
            {metric.label}
          </span>
          <div className="flex items-end justify-between mt-2">
            <div className="flex items-baseline gap-1">
              <span className={`text-xl font-semibold tracking-tighter ${metric.color}`}>
                {metric.value}
              </span>
              <span className="text-xs text-gray-600">{metric.unit}</span>
            </div>
            <span className="text-[10px] font-mono text-gray-500">{metric.trend}</span>
          </div>
        </motion.div>
      ))}
    </motion.div>
  );
}
