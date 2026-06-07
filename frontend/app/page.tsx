"use client";
import React, { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ShieldAlert, Cpu, Search, CheckCircle2, Send, Activity, Terminal, Database } from "lucide-react";

export default function ObsidianCommandCenter() {
  // --- CORE STATE ---
  const [ws, setWs] = useState<WebSocket | null>(null);
  const [systemStatus, setSystemStatus] = useState("DORMANT");
  const [chatInput, setChatInput] = useState("");
  const [chatLog, setChatLog] = useState<{ role: string; content: string }[]>([]);
  const [guardrailPayload, setGuardrailPayload] = useState<any>(null);
  const [logs, setLogs] = useState<string[]>(["[SYSTEM] > Neural Tether Initializing..."]);

  // --- DATA INGESTION STATE ---
  const [activeDbName, setActiveDbName] = useState("No DB Mounted");
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  
  // --- LIVE DB TETHER STATE ---
  const [showLiveDbModal, setShowLiveDbModal] = useState(false);
  const [liveDbUri, setLiveDbUri] = useState("");
  const [isLinking, setIsLinking] = useState(false);

  // --- WEBSOCKET TETHER ---
  useEffect(() => {
    const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws/sage";
    const socket = new WebSocket(WS_URL);
    
    socket.onopen = () => { 
      setSystemStatus("ONLINE"); 
      setWs(socket); 
      setLogs(p => [...p, "[SYSTEM] > Tether connection established."]);
    };
    
    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "node_update") setLogs(p => [...p, `[AGENT] > Executing ${data.node}...`]);
      else if (data.type === "chat_response") setChatLog((prev) => [...prev, { role: "SageCommand", content: data.text }]); 
      else if (data.type === "log") setLogs(p => [...p, data.message]);
      else if (data.type === "guardrail_interrupt") { 
        setGuardrailPayload(data.payload); 
        setSystemStatus("INTERRUPTED"); 
        setLogs(p => [...p, "[WARN] > Execution halted by Heuristic Evaluator."]);
      }
      else if (data.type === "status") setSystemStatus(data.status); 
    };
    
    socket.onclose = () => {
        setSystemStatus("OFFLINE");
        setLogs(p => [...p, "[ERROR] > Tether disconnected."]);
    };
    return () => socket.close();
  }, []);

  // --- COMMAND ACTIONS ---
  const triggerScan = () => { 
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setLogs(p => [...p, "[ERROR] > Cannot scan. Neural Tether is disconnected."]);
      return;
    }
    ws.send(JSON.stringify({ command: "scan" })); 
    setGuardrailPayload(null); 
    setLogs(p => [...p, "[SYSTEM] > Force manual scan initiated."]);
  };
  
  const approveExecution = () => { 
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setLogs(p => [...p, "[ERROR] > Cannot approve. Neural Tether is disconnected."]);
      return;
    }
    ws.send(JSON.stringify({ command: "approve" })); 
    setGuardrailPayload(null);
    setLogs(p => [...p, "[SYSTEM] > Human authorization granted. Executing payload."]);
  };

  // --- DATACORE FILE UPLOAD HANDLER ---
  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    setLogs(p => [...p, `[SYSTEM] > Initiating uplink for ${file.name}...`]);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch("http://localhost:8000/upload-db", {
        method: "POST",
        body: formData,
      });
      const data = await response.json();

      if (data.status === "success") {
        setActiveDbName(file.name);
        setLogs(p => [...p, `[SUCCESS] > ${data.message}`]);
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ command: "chat", text: `I just uploaded a new dataset named ${file.name}. List all the tables inside it.` }));
        }
      } else {
        setLogs(p => [...p, `[ERROR] > ${data.message}`]);
      }
    } catch (error) {
      setLogs(p => [...p, `[ERROR] > Datacore uplink failed.`]);
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // --- LIVE DB CONNECTION HANDLER ---
  const handleLiveDbConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!liveDbUri.trim()) return;

    setIsLinking(true);
    setLogs(p => [...p, `[SYSTEM] > Establishing secure tunnel to live database...`]);

    try {
      const response = await fetch("http://localhost:8000/connect-live-db", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ connection_string: liveDbUri }),
      });
      const data = await response.json();
      
      if (data.status === "success") {
        setActiveDbName("LIVE: " + (liveDbUri.split('@')[1]?.split('/')[0] || "Remote Node"));
        setLogs(p => [...p, `[SUCCESS] > ${data.message}`]);
        setShowLiveDbModal(false);
        setLiveDbUri("");
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ command: "chat", text: `I just connected a live database. Please map the schema and tell me what tables we have.` }));
        }
      } else {
        setLogs(p => [...p, `[ERROR] > ${data.message}`]);
      }
    } catch (error) {
      setLogs(p => [...p, `[ERROR] > Live tether failed. Check network routing.`]);
    } finally {
      setIsLinking(false);
    }
  };

  return (
    <div className="w-screen h-screen bg-[#020202] text-gray-300 font-sans overflow-hidden flex flex-col selection:bg-cyan-500/30">
      
      {/* --- OMNI-HEADER --- */}
      <header className="h-14 border-b border-white/5 flex items-center justify-between px-6 bg-[#050505]">
        <div className="flex items-center gap-4">
          <div className={`w-2 h-2 rounded-full ${systemStatus === 'ONLINE' ? 'bg-cyan-500 animate-pulse shadow-[0_0_10px_rgba(6,182,212,0.6)]' : 'bg-red-500 shadow-[0_0_10px_rgba(239,68,68,0.6)]'}`} />
          <span className="font-mono text-xs uppercase tracking-[0.2em] text-cyan-500 font-bold">Sage OS // V2.0</span>
        </div>
        
        <div className="flex items-center gap-3">
          {/* Active Database Indicator */}
          <div className="flex items-center gap-2 px-3 py-1.5 bg-black/50 border border-white/5 rounded text-[10px] font-mono text-gray-400 mr-2 shadow-inner">
            <Database className="w-3 h-3 text-gray-500" />
            {activeDbName}
          </div>

          {/* Mount Local File Button (NOW ACCEPTS CSV) */}
          <input type="file" ref={fileInputRef} onChange={handleFileUpload} accept=".sqlite,.db,.csv" className="hidden" />
          <button 
            type="button"
            onClick={() => fileInputRef.current?.click()} 
            disabled={isUploading}
            className={`flex items-center gap-2 px-4 py-1.5 border rounded transition-colors text-[10px] font-mono uppercase tracking-widest ${isUploading ? 'bg-purple-500/10 text-purple-400 border-purple-500/20 animate-pulse' : 'bg-white/[0.02] text-gray-400 border-white/10 hover:bg-white/5 hover:text-white'}`}
          >
            <Terminal className="w-3 h-3" /> {isUploading ? "Uploading..." : "Mount File"}
          </button>

          {/* Link Live DB Button */}
          <button 
            type="button"
            onClick={() => setShowLiveDbModal(true)} 
            className="flex items-center gap-2 px-4 py-1.5 border border-purple-500/30 bg-purple-500/10 text-purple-400 rounded hover:bg-purple-500/20 transition-colors text-[10px] font-mono uppercase tracking-widest"
          >
            <Activity className="w-3 h-3" /> Live Uplink
          </button>

          {/* Force Scan Button */}
          <button type="button" onClick={triggerScan} className="flex items-center gap-2 px-4 py-1.5 bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 rounded hover:bg-cyan-500/20 transition-colors text-[10px] font-mono uppercase tracking-widest ml-4">
            <Activity className="w-3 h-3" /> Core Scan
          </button>
        </div>
      </header>

      {/* --- BENTO GRID LAYOUT --- */}
      <main className="flex-1 grid grid-cols-12 grid-rows-6 gap-4 p-4">
        
        {/* METRICS ROW */}
        <div className="col-span-8 row-span-1 grid grid-cols-3 gap-4">
          {[
            { label: "System Status", value: systemStatus, unit: "", trend: "Live", color: systemStatus === "INTERRUPTED" ? "text-red-400" : "text-cyan-400" },
            { label: "AI Confidence Matrix", value: "99.8", unit: "%", trend: "Optimal", color: "text-green-400" },
            { label: "Active Threat Vectors", value: guardrailPayload ? "1" : "0", unit: "Detected", trend: guardrailPayload ? "Action Req" : "Secured", color: guardrailPayload ? "text-red-400" : "text-gray-400" }
          ].map((metric, i) => (
            <div key={i} className="bg-zinc-950 border border-white/5 rounded-xl p-4 flex flex-col justify-between hover:border-white/10 transition-colors relative overflow-hidden">
              <div className="absolute top-0 right-0 w-16 h-16 bg-white/[0.01] rounded-full blur-xl -mr-8 -mt-8" />
              <span className="text-[10px] font-mono uppercase tracking-widest text-gray-500">{metric.label}</span>
              <div className="flex items-end justify-between">
                <div className="flex items-baseline gap-1">
                  <span className={`text-xl font-semibold tracking-tighter ${metric.color}`}>{metric.value}</span>
                  <span className="text-xs text-gray-600">{metric.unit}</span>
                </div>
                <span className="text-[10px] font-mono text-gray-500">{metric.trend}</span>
              </div>
            </div>
          ))}
        </div>

        {/* COPILOT STRATEGY CORTEX */}
        <div className="col-span-4 row-span-6 bg-[#070707] border border-white/5 rounded-xl flex flex-col overflow-hidden shadow-2xl relative">
           <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-purple-500/50 to-transparent" />
           <div className="p-4 border-b border-white/5 flex items-center justify-between bg-zinc-950/50">
             <div className="flex items-center gap-2">
               <Cpu className="w-4 h-4 text-purple-400" />
               <span className="text-xs font-bold uppercase tracking-wider text-white">Strategic Copilot</span>
             </div>
             <span className="text-[9px] font-mono bg-purple-500/10 text-purple-400 px-2 py-0.5 rounded border border-purple-500/20">LIVE TETHER</span>
           </div>
           
           <div className="flex-1 p-4 flex flex-col gap-4 overflow-y-auto font-mono text-xs scrollbar-hide">
             {chatLog.length === 0 && (
               <div className="text-gray-600 text-center mt-10">Awaiting strategic queries...</div>
             )}
             {chatLog.map((msg, idx) => (
               <motion.div 
                 key={idx} 
                 initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} 
                 className={`p-3 rounded-lg border max-w-[90%] ${
                   msg.role === 'User' 
                     ? 'bg-white/5 border-white/10 rounded-tr-none self-end text-gray-300' 
                     : 'bg-purple-900/10 border-purple-500/20 rounded-tl-none self-start text-purple-200 shadow-[0_0_15px_rgba(168,85,247,0.05)]'
                 }`}
               >
                 <span className={`text-[9px] uppercase tracking-widest block mb-1.5 ${msg.role === 'User' ? 'text-gray-500 text-right' : 'text-purple-400'}`}>
                   {msg.role}
                 </span>
                 {msg.content}
               </motion.div>
             ))}
           </div>

           <form 
             onSubmit={(e) => { 
               e.preventDefault(); 
               if (chatInput.trim() && ws?.readyState === WebSocket.OPEN) { 
                 ws.send(JSON.stringify({ command: "chat", text: chatInput })); 
                 setChatLog(prev => [...prev, { role: "User", content: chatInput }]); 
                 setChatInput(""); 
               } 
             }} 
             className="p-3 border-t border-white/5 bg-zinc-950 relative flex items-center group"
           >
             <input 
               type="text" 
               value={chatInput}
               onChange={e => setChatInput(e.target.value)}
               placeholder="Command AI Agent... (Press Enter)" 
               className="w-full bg-[#030303] border border-white/10 rounded-md py-2.5 pl-3 pr-10 text-xs focus:outline-none focus:border-purple-500/50 placeholder:text-gray-700 font-mono transition-colors" 
             />
             <button type="submit" disabled={!chatInput.trim()} className="absolute right-5 p-1 text-gray-600 hover:text-purple-400 disabled:opacity-30 disabled:hover:text-gray-600 transition-colors">
               <Send className="w-4 h-4" />
             </button>
           </form>
        </div>

        {/* OMNI-FEED / EXECUTION TERMINAL */}
        <div className="col-span-8 row-span-5 bg-zinc-950 border border-white/5 rounded-xl flex flex-col overflow-hidden">
          <div className="flex items-center border-b border-white/5 bg-[#050505]">
            <button type="button" className="flex items-center gap-2 px-4 py-3 text-xs font-mono uppercase tracking-widest text-cyan-400 border-b-2 border-cyan-400 bg-white/[0.02]">
              <Terminal className="w-3 h-3" /> Execution Feed
            </button>
          </div>
          
          <div className="flex-1 p-5 font-mono text-xs overflow-y-auto flex flex-col gap-3">
            <div className="flex items-start gap-4 p-3 hover:bg-white/[0.02] rounded-lg transition-colors group">
              <CheckCircle2 className="w-4 h-4 text-green-500 mt-0.5 shrink-0" />
              <div>
                <p className="text-gray-300 font-semibold mb-1">Verify Boot Signatures</p>
                <p className="text-gray-500 text-[10px]">Neural core and local dependencies authenticated.</p>
              </div>
            </div>

            {/* GUARDRAIL INTERRUPT */}
            <AnimatePresence>
              {guardrailPayload && (
                <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.98 }} className="flex items-start gap-4 p-4 bg-red-500/[0.03] border border-red-500/20 rounded-lg shadow-[0_0_30px_rgba(239,68,68,0.05)] mt-2">
                  <ShieldAlert className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
                  <div className="flex-1">
                    <p className="text-red-400 font-bold mb-1 uppercase tracking-wider text-sm">Execution Halted (PENDING)</p>
                    <div className="bg-black/50 p-3 rounded border border-red-500/10 my-3">
                      <p className="text-gray-500 text-[10px] uppercase mb-1">Proposed AI Action:</p>
                      <p className="text-white text-sm mb-2">{">"} {guardrailPayload.action}</p>
                      <p className="text-gray-500 text-[10px] uppercase mb-1">AI Logic Justification:</p>
                      <p className="text-gray-400">{guardrailPayload.justification}</p>
                    </div>
                    <div className="flex gap-3 mt-4">
                      <button type="button" onClick={approveExecution} className="px-4 py-2 bg-red-500 text-black font-bold uppercase tracking-widest text-[10px] rounded hover:bg-red-400 transition-colors shadow-[0_0_15px_rgba(239,68,68,0.4)]">Authorize Action</button>
                      <button type="button" onClick={() => setGuardrailPayload(null)} className="px-4 py-2 border border-white/10 text-gray-400 font-bold uppercase tracking-widest text-[10px] rounded hover:bg-white/5 transition-colors">Abort Sequence</button>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* RAW CONSOLE LOGS */}
            <div className="mt-auto pt-4 border-t border-white/5">
              <div className="p-4 bg-[#020202] border border-white/5 rounded-lg text-[10px] leading-relaxed text-gray-500 font-mono shadow-inner h-32 overflow-y-auto flex flex-col-reverse">
                <div>
                  {logs.map((log, i) => (
                    <p key={i} className={log.includes('[WARN]') || log.includes('[ERROR]') ? 'text-red-400' : log.includes('[AGENT]') || log.includes('[SUCCESS]') ? 'text-purple-400' : 'text-gray-400'}>
                      {log}
                    </p>
                  ))}
                  <motion.div animate={{ opacity: [1, 0] }} transition={{ repeat: Infinity, duration: 0.8 }} className="w-2 h-3 bg-gray-500 mt-1 inline-block" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* --- LIVE DATABASE MODAL --- */}
      <AnimatePresence>
        {showLiveDbModal && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
            <motion.div initial={{ scale: 0.95, y: 20 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.95, y: 20 }} className="w-[500px] bg-[#050505] border border-white/10 rounded-2xl shadow-[0_0_50px_rgba(0,0,0,0.8)] overflow-hidden">
              <div className="p-5 border-b border-white/5 flex justify-between items-center bg-zinc-950">
                <h3 className="text-sm font-bold uppercase tracking-widest text-purple-400">Establish Live Tether</h3>
                <button type="button" onClick={() => setShowLiveDbModal(false)} className="text-gray-500 hover:text-white">✕</button>
              </div>
              <form onSubmit={handleLiveDbConnect} className="p-6">
                <p className="text-xs text-gray-500 font-mono mb-4">
                  Inject a valid connection string (PostgreSQL, MySQL, AWS RDS) to route the AI&apos;s visual cortex to a live production cluster.
                </p>
                <input 
                  type="password" 
                  value={liveDbUri}
                  onChange={(e) => setLiveDbUri(e.target.value)}
                  placeholder="postgresql://user:password@localhost:5432/dbname" 
                  className="w-full bg-[#020202] border border-white/10 rounded py-3 px-4 text-xs font-mono text-white focus:outline-none focus:border-purple-500 transition-colors mb-6"
                />
                <div className="flex justify-end gap-3">
                  <button type="button" onClick={() => setShowLiveDbModal(false)} className="px-4 py-2 text-xs font-mono uppercase text-gray-400 hover:text-white">Cancel</button>
                  <button type="submit" disabled={isLinking || !liveDbUri} className="px-6 py-2 bg-purple-500 text-black font-bold uppercase tracking-widest text-xs rounded hover:bg-purple-400 disabled:opacity-50 transition-colors shadow-[0_0_15px_rgba(168,85,247,0.3)]">
                    {isLinking ? "Connecting..." : "Initialize Link"}
                  </button>
                </div>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

    </div>
  );
}