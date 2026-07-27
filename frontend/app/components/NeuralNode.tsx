"use client";
import React from "react";
import { Handle, Position } from "reactflow";
import { motion } from "framer-motion";

interface NeuralNodeData {
  label: string;
  icon: string;
  isActive: boolean;
  variant?: "default" | "warning" | "threat" | "success";
}

const variantStyles = {
  default: {
    active: "bg-cyan-500/10 border-cyan-400 shadow-neon-cyan",
    idle: "bg-white/[0.02] border-white/[0.06] hover:border-white/20",
    textActive: "text-cyan-400",
    dotColor: "bg-cyan-400",
    ringColor: "border-cyan-400/40",
  },
  warning: {
    active: "bg-amber-500/10 border-amber-400 shadow-neon-amber",
    idle: "bg-white/[0.02] border-white/[0.06] hover:border-white/20",
    textActive: "text-amber-400",
    dotColor: "bg-amber-400",
    ringColor: "border-amber-400/40",
  },
  threat: {
    active: "bg-red-500/10 border-red-400 shadow-neon-red",
    idle: "bg-white/[0.02] border-white/[0.06] hover:border-white/20",
    textActive: "text-red-400",
    dotColor: "bg-red-400",
    ringColor: "border-red-400/40",
  },
  success: {
    active: "bg-green-500/10 border-green-400",
    idle: "bg-white/[0.02] border-white/[0.06] hover:border-white/20",
    textActive: "text-green-400",
    dotColor: "bg-green-400",
    ringColor: "border-green-400/40",
  },
};

export default function NeuralNode({ data }: { data: NeuralNodeData }) {
  const variant = data.variant || "default";
  const styles = variantStyles[variant];
  const isActive = data.isActive;

  return (
    <motion.div
      initial={{ scale: 0.85, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ type: "spring", stiffness: 260, damping: 20 }}
      className="relative"
    >
      {/* Pulsing concentric ring when active */}
      {isActive && (
        <>
          <motion.div
            className={`absolute inset-0 rounded-2xl border ${styles.ringColor}`}
            initial={{ scale: 1, opacity: 0.6 }}
            animate={{ scale: 1.35, opacity: 0 }}
            transition={{ duration: 2, repeat: Infinity, ease: "easeOut" }}
          />
          <motion.div
            className={`absolute inset-0 rounded-2xl border ${styles.ringColor}`}
            initial={{ scale: 1, opacity: 0.4 }}
            animate={{ scale: 1.6, opacity: 0 }}
            transition={{ duration: 2, repeat: Infinity, ease: "easeOut", delay: 0.6 }}
          />
        </>
      )}

      <div
        className={`relative min-w-[180px] px-5 py-4 rounded-2xl backdrop-blur-xl border-2 transition-all duration-500 ${
          isActive ? styles.active : styles.idle
        } ${isActive ? "node-active-glow" : ""}`}
      >
        <Handle
          type="target"
          position={Position.Top}
          className="!bg-gray-600 !w-2 !h-2 !border-none !-top-1"
        />

        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between mb-1.5">
            <span
              className={`text-[9px] font-black tracking-[0.15em] uppercase ${
                isActive ? styles.textActive : "text-gray-600"
              }`}
            >
              {isActive ? "ACTIVE" : "STANDBY"}
            </span>
            <div
              className={`w-1.5 h-1.5 rounded-full transition-colors duration-300 ${
                isActive ? `${styles.dotColor} status-dot-breathe` : "bg-gray-700"
              }`}
            />
          </div>

          <div className="flex items-center gap-3">
            <div className="text-2xl filter drop-shadow-md select-none">
              {data.icon}
            </div>
            <div className="text-xs font-bold text-white tracking-tight leading-tight">
              {data.label}
            </div>
          </div>
        </div>

        <Handle
          type="source"
          position={Position.Bottom}
          className="!bg-gray-600 !w-2 !h-2 !border-none !-bottom-1"
        />
      </div>
    </motion.div>
  );
}