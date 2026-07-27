"use client";
import React, { useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Cpu, Send } from "lucide-react";

interface ChatMessage {
  role: string;
  content: string;
}

interface CopilotPanelProps {
  chatLog: ChatMessage[];
  chatInput: string;
  onChatInputChange: (value: string) => void;
  onSendMessage: (e: React.FormEvent) => void;
  isConnected: boolean;
}

export default function CopilotPanel({
  chatLog,
  chatInput,
  onChatInputChange,
  onSendMessage,
  isConnected,
}: CopilotPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [chatLog]);

  return (
    <div className="bg-[#070707] border border-white/5 rounded-xl flex flex-col overflow-hidden shadow-2xl relative h-full">
      {/* Top accent gradient */}
      <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-purple-500/50 to-transparent" />

      {/* Header */}
      <div className="p-4 border-b border-white/5 flex items-center justify-between bg-zinc-950/50">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-purple-400" />
          <span className="text-xs font-bold uppercase tracking-wider text-white">
            Strategic Copilot
          </span>
        </div>
        <motion.span
          animate={{ opacity: [0.7, 1, 0.7] }}
          transition={{ duration: 2, repeat: Infinity }}
          className="text-[9px] font-mono bg-purple-500/10 text-purple-400 px-2 py-0.5 rounded border border-purple-500/20"
        >
          LIVE TETHER
        </motion.span>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex-1 p-4 flex flex-col gap-3 overflow-y-auto font-mono text-xs scrollbar-hide"
      >
        {chatLog.length === 0 && (
          <div className="text-gray-600 text-center mt-10 flex flex-col items-center gap-2">
            <motion.div
              animate={{ opacity: [0.3, 0.6, 0.3] }}
              transition={{ duration: 3, repeat: Infinity }}
            >
              <Cpu className="w-8 h-8 text-gray-700" />
            </motion.div>
            <span>Awaiting strategic queries...</span>
          </div>
        )}
        <AnimatePresence initial={false}>
          {chatLog.map((msg, idx) => (
            <motion.div
              key={idx}
              initial={{ opacity: 0, y: 15, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ type: "spring", stiffness: 350, damping: 25 }}
              className={`p-3 rounded-lg border max-w-[90%] ${
                msg.role === "User"
                  ? "bg-white/5 border-white/10 rounded-tr-none self-end text-gray-300"
                  : "bg-purple-900/10 border-purple-500/20 rounded-tl-none self-start text-purple-200 shadow-[0_0_15px_rgba(168,85,247,0.05)]"
              }`}
            >
              <span
                className={`text-[9px] uppercase tracking-widest block mb-1.5 ${
                  msg.role === "User" ? "text-gray-500 text-right" : "text-purple-400"
                }`}
              >
                {msg.role}
              </span>
              <span className="whitespace-pre-wrap break-words">{msg.content}</span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* Input */}
      <form
        onSubmit={onSendMessage}
        className="p-3 border-t border-white/5 bg-zinc-950 relative flex items-center"
      >
        <input
          type="text"
          value={chatInput}
          onChange={(e) => onChatInputChange(e.target.value)}
          placeholder="Command AI Agent... (Press Enter)"
          className="w-full bg-[#030303] border border-white/10 rounded-md py-2.5 pl-3 pr-10 text-xs focus:outline-none focus:border-purple-500/50 placeholder:text-gray-700 font-mono transition-colors"
        />
        <motion.button
          type="submit"
          disabled={!chatInput.trim()}
          whileHover={{ scale: 1.15 }}
          whileTap={{ scale: 0.9 }}
          className="absolute right-5 p-1 text-gray-600 hover:text-purple-400 disabled:opacity-30 disabled:hover:text-gray-600 transition-colors"
        >
          <Send className="w-4 h-4" />
        </motion.button>
      </form>
    </div>
  );
}
