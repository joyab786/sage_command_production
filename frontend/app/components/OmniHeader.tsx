"use client";
import React from "react";
import { motion } from "framer-motion";
import { Activity, Terminal, Database, Search } from "lucide-react";

interface OmniHeaderProps {
  systemStatus: string;
  activeDbName: string;
  isUploading: boolean;
  isAnalyzingImage: boolean;
  userRole: "operator" | "manager";
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  imageInputRef: React.RefObject<HTMLInputElement | null>;
  onFileUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onImageUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onMountFileClick: () => void;
  onLiveUplinkClick: () => void;
  onTimeTravelClick: () => void;
  onHardwareVisionClick: () => void;
  onCoreScanClick: () => void;
  onRoleChange: (role: "operator" | "manager") => void;
}

export default function OmniHeader({
  systemStatus,
  activeDbName,
  isUploading,
  isAnalyzingImage,
  userRole,
  fileInputRef,
  imageInputRef,
  onFileUpload,
  onImageUpload,
  onMountFileClick,
  onLiveUplinkClick,
  onTimeTravelClick,
  onHardwareVisionClick,
  onCoreScanClick,
  onRoleChange,
}: OmniHeaderProps) {
  const isOnline = systemStatus === "ONLINE";

  return (
    <header className="h-14 border-b border-white/5 flex items-center justify-between px-6 bg-[#050505] relative overflow-hidden">
      {/* Subtle bottom glow line */}
      <div className="absolute bottom-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-cyan-500/20 to-transparent" />

      {/* Left: Brand */}
      <div className="flex items-center gap-4">
        <motion.div
          animate={
            isOnline
              ? {
                  boxShadow: [
                    "0 0 4px rgba(6,182,212,0.3)",
                    "0 0 12px rgba(6,182,212,0.6)",
                    "0 0 4px rgba(6,182,212,0.3)",
                  ],
                }
              : {}
          }
          transition={{ duration: 2, repeat: Infinity }}
          className={`w-2 h-2 rounded-full ${
            isOnline
              ? "bg-cyan-500"
              : systemStatus === "LOCKDOWN"
              ? "bg-red-500 shadow-[0_0_10px_rgba(239,68,68,0.6)]"
              : "bg-red-500 shadow-[0_0_10px_rgba(239,68,68,0.6)]"
          }`}
        />
        <span className="font-mono text-xs uppercase tracking-[0.2em] text-cyan-500 font-bold">
          Sage OS // V2.0
        </span>
      </div>

      {/* Right: Controls */}
      <div className="flex items-center gap-2.5">
        {/* Active Database */}
        <div className="flex items-center gap-2 px-3 py-1.5 bg-black/50 border border-white/5 rounded text-[10px] font-mono text-gray-400 mr-1 shadow-inner">
          <Database className="w-3 h-3 text-gray-500" />
          {activeDbName}
        </div>

        {/* Mount File */}
        <input
          type="file"
          ref={fileInputRef}
          onChange={onFileUpload}
          accept=".sqlite,.db,.csv"
          className="hidden"
        />
        <HeaderButton
          onClick={onMountFileClick}
          disabled={isUploading}
          active={isUploading}
          activeClass="bg-purple-500/10 text-purple-400 border-purple-500/20 animate-pulse"
          icon={<Terminal className="w-3 h-3" />}
          label={isUploading ? "Uploading..." : "Mount File"}
        />

        {/* Live Uplink */}
        <HeaderButton
          onClick={onLiveUplinkClick}
          active={false}
          activeClass=""
          className="border-purple-500/30 bg-purple-500/10 text-purple-400 hover:bg-purple-500/20"
          icon={<Activity className="w-3 h-3" />}
          label="Live Uplink"
        />

        {/* Time Travel */}
        <HeaderButton
          onClick={onTimeTravelClick}
          active={false}
          activeClass=""
          className="border-cyan-500/30 bg-cyan-500/10 text-cyan-400 hover:bg-cyan-500/20"
          icon={<Terminal className="w-3 h-3 text-cyan-400" />}
          label="Time Travel"
        />

        {/* Hardware Vision */}
        <input
          type="file"
          ref={imageInputRef}
          onChange={onImageUpload}
          accept="image/*"
          className="hidden"
        />
        <HeaderButton
          onClick={onHardwareVisionClick}
          disabled={isAnalyzingImage}
          active={isAnalyzingImage}
          activeClass="bg-amber-500/10 text-amber-400 border-amber-500/30 animate-pulse"
          icon={<Search className="w-3 h-3 text-amber-400" />}
          label={isAnalyzingImage ? "Analyzing..." : "Hardware Vision"}
        />

        {/* RBAC Role Toggle */}
        <div className="flex items-center bg-black/60 border border-white/10 rounded p-0.5 font-mono text-[10px] relative">
          {/* Sliding highlight */}
          <motion.div
            layout
            className={`absolute h-[calc(100%-4px)] w-[calc(50%-2px)] rounded ${
              userRole === "operator"
                ? "bg-zinc-800 border border-cyan-500/30 left-[2px]"
                : "bg-purple-950/80 border border-purple-500/40 left-[calc(50%)]"
            }`}
            transition={{ type: "spring", stiffness: 500, damping: 35 }}
          />
          <button
            type="button"
            onClick={() => onRoleChange("operator")}
            className={`relative z-10 px-2.5 py-1 rounded uppercase tracking-wider transition-colors ${
              userRole === "operator"
                ? "text-cyan-400 font-bold"
                : "text-gray-500 hover:text-gray-300"
            }`}
          >
            Operator
          </button>
          <button
            type="button"
            onClick={() => onRoleChange("manager")}
            className={`relative z-10 px-2.5 py-1 rounded uppercase tracking-wider transition-colors ${
              userRole === "manager"
                ? "text-purple-400 font-bold"
                : "text-gray-500 hover:text-gray-300"
            }`}
          >
            Manager
          </button>
        </div>

        {/* Core Scan */}
        <motion.button
          type="button"
          onClick={onCoreScanClick}
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          className="flex items-center gap-2 px-4 py-1.5 bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 rounded hover:bg-cyan-500/20 transition-colors text-[10px] font-mono uppercase tracking-widest ml-1"
        >
          <Activity className="w-3 h-3" /> Core Scan
        </motion.button>
      </div>
    </header>
  );
}

/* Reusable header button */
function HeaderButton({
  onClick,
  disabled,
  active,
  activeClass,
  className,
  icon,
  label,
}: {
  onClick: () => void;
  disabled?: boolean;
  active?: boolean;
  activeClass?: string;
  className?: string;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      disabled={disabled}
      whileHover={!disabled ? { scale: 1.05 } : undefined}
      whileTap={!disabled ? { scale: 0.95 } : undefined}
      className={`flex items-center gap-2 px-3.5 py-1.5 border rounded transition-colors text-[10px] font-mono uppercase tracking-widest ${
        active && activeClass
          ? activeClass
          : className || "bg-white/[0.02] text-gray-400 border-white/10 hover:bg-white/5 hover:text-white"
      }`}
    >
      {icon} {label}
    </motion.button>
  );
}
