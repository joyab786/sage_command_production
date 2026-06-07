"use client";
import React from 'react';
import { Handle, Position } from 'reactflow';
import { motion } from 'framer-motion';

export default function NeuralNode({ data }: any) {
  return (
    <motion.div
      initial={{ scale: 0.9, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      className={`relative min-w-[220px] px-6 py-5 rounded-2xl backdrop-blur-xl transition-all duration-500 ${
        data.isActive
          ? 'bg-green-500/10 border-2 border-green-400 shadow-[0_0_40px_rgba(51,255,0,0.25)]'
          : 'bg-white/[0.03] border border-white/10 hover:border-white/30 shadow-2xl'
      }`}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-600 !w-2 !h-2 !border-none" />
      
      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between mb-2">
          <span className={`text-[10px] font-black tracking-[0.2em] uppercase ${data.isActive ? 'text-green-400' : 'text-gray-500'}`}>
            {data.isActive ? 'Active Intelligence' : 'System Standby'}
          </span>
          <div className={`w-2 h-2 rounded-full ${data.isActive ? 'bg-green-400 animate-pulse' : 'bg-gray-700'}`} />
        </div>
        
        <div className="flex items-center gap-4">
          <div className="text-3xl filter drop-shadow-md">{data.icon}</div>
          <div className="text-sm font-bold text-white tracking-tight">{data.label}</div>
        </div>
      </div>

      <Handle type="source" position={Position.Bottom} className="!bg-gray-600 !w-2 !h-2 !border-none" />
    </motion.div>
  );
}