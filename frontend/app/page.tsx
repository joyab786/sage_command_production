"use client";
import React, { useState, useEffect, useRef } from "react";
import { motion } from "framer-motion";

// Components
import OmniHeader from "./components/OmniHeader";
import MetricsRow from "./components/MetricsRow";
import NeuralFlowGraph from "./components/NeuralFlowGraph";
import CopilotPanel from "./components/CopilotPanel";
import ExecutionFeed from "./components/ExecutionFeed";
import LiveDbModal from "./components/LiveDbModal";
import TimelineModal from "./components/TimelineModal";
import SecurityAlertModal from "./components/SecurityAlertModal";

export default function ObsidianCommandCenter() {
  // --- CORE STATE ---
  const [ws, setWs] = useState<WebSocket | null>(null);
  const [systemStatus, setSystemStatus] = useState("DORMANT");
  const [chatInput, setChatInput] = useState("");
  const [chatLog, setChatLog] = useState<{ role: string; content: string }[]>([]);
  const [guardrailPayload, setGuardrailPayload] = useState<any>(null);
  const [logs, setLogs] = useState<string[]>(["[SYSTEM] > Neural Tether Initializing..."]);
  const [activeNode, setActiveNode] = useState<string | null>(null);

  // --- DATA INGESTION STATE ---
  const [activeDbName, setActiveDbName] = useState("No DB Mounted");
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // --- LIVE DB TETHER STATE ---
  const [showLiveDbModal, setShowLiveDbModal] = useState(false);
  const [liveDbUri, setLiveDbUri] = useState("");
  const [isLinking, setIsLinking] = useState(false);

  // --- TIME TRAVEL STATE ---
  const [showTimelineModal, setShowTimelineModal] = useState(false);
  const [checkpointHistory, setCheckpointHistory] = useState<any[]>([]);

  // --- SECURITY INTRUSION ALERT STATE ---
  const [securityAlert, setSecurityAlert] = useState<{
    threat_level: string;
    details: string;
  } | null>(null);

  // --- BLAST RADIUS & RBAC STATE ---
  const [blastRadiusData, setBlastRadiusData] = useState<any>(null);
  const [userRole, setUserRole] = useState<"operator" | "manager">("operator");

  // --- MULTI-MODAL VISION STATE ---
  const [visionFinding, setVisionFinding] = useState<any>(null);
  const [isAnalyzingImage, setIsAnalyzingImage] = useState(false);
  const imageInputRef = useRef<HTMLInputElement>(null);

  // --- WEBSOCKET TETHER ---
  useEffect(() => {
    const WS_URL =
      process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws/sage";
    const socket = new WebSocket(WS_URL);

    socket.onopen = () => {
      setSystemStatus("ONLINE");
      setWs(socket);
      setLogs((p) => [...p, "[SYSTEM] > Tether connection established."]);
    };

    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === "node_update") {
        setLogs((p) => [...p, `[AGENT] > Executing ${data.node}...`]);
      } else if (data.type === "node_active") {
        setActiveNode(data.node);
        setLogs((p) => [...p, `[TELEMETRY] > Active Node: ${data.node}`]);
      } else if (data.type === "vision_result") {
        setVisionFinding(data.data);
        setIsAnalyzingImage(false);
        setLogs((p) => [
          ...p,
          `[VISION CORTEX] > Hardware Diagnosed: ${data.data?.part_identified}`,
        ]);
      } else if (data.type === "security_alert") {
        setSecurityAlert({
          threat_level: data.threat_level,
          details: data.details,
        });
        setSystemStatus("LOCKDOWN");
        setActiveNode(null);
        setLogs((p) => [
          ...p,
          `[CRITICAL SECURITY ALERT] > Threat Intercepted: ${data.details}`,
        ]);
      } else if (data.type === "blast_radius_data") {
        setBlastRadiusData(data.data);
        setLogs((p) => [
          ...p,
          `[RISK CORTEX] > Mapped Blast Radius: Urgency ${data.data?.urgency_rating}`,
        ]);
      } else if (data.type === "graph_status") {
        if (data.status === "INTERRUPTED") {
          setSystemStatus("INTERRUPTED");
          setActiveNode(null);
          setLogs((p) => [
            ...p,
            `[WARN] > Execution interrupted before '${data.node}' node.`,
          ]);
        }
      } else if (data.type === "unauthorized") {
        setLogs((p) => [...p, `[SECURITY ERROR] > ${data.message}`]);
      } else if (data.type === "chat_response") {
        setChatLog((prev) => [
          ...prev,
          { role: "SageCommand", content: data.text },
        ]);
        setActiveNode(null);
      } else if (data.type === "checkpoint_history") {
        setCheckpointHistory(data.history || []);
        setLogs((p) => [
          ...p,
          `[TIMELINE] > Retrieved ${data.history?.length || 0} state checkpoints.`,
        ]);
      } else if (data.type === "log") {
        setLogs((p) => [...p, data.message]);
      } else if (data.type === "guardrail_interrupt") {
        setGuardrailPayload(data.payload);
        setSystemStatus("INTERRUPTED");
        setLogs((p) => [
          ...p,
          "[WARN] > Execution halted by Heuristic Evaluator.",
        ]);
      } else if (data.type === "status") {
        setSystemStatus(data.status);
        if (data.status === "ONLINE") {
          setActiveNode(null);
        }
      }
    };

    socket.onclose = () => {
      setSystemStatus("OFFLINE");
      setLogs((p) => [...p, "[ERROR] > Tether disconnected."]);
    };

    return () => socket.close();
  }, []);

  // --- COMMAND ACTIONS ---
  const triggerScan = () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setLogs((p) => [
        ...p,
        "[ERROR] > Cannot scan. Neural Tether is disconnected.",
      ]);
      return;
    }
    ws.send(JSON.stringify({ command: "scan" }));
    setGuardrailPayload(null);
    setActiveNode(null);
    setLogs((p) => [...p, "[SYSTEM] > Force manual scan initiated."]);
  };

  const approveExecution = () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setLogs((p) => [
        ...p,
        "[ERROR] > Cannot approve. Neural Tether is disconnected.",
      ]);
      return;
    }
    ws.send(JSON.stringify({ command: "approve", user_role: userRole }));
    setLogs((p) => [
      ...p,
      `[SYSTEM] > Authorization requested by role: ${userRole.toUpperCase()}`,
    ]);
  };

  const handleImageUpload = (
    event: React.ChangeEvent<HTMLInputElement>
  ) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setLogs((p) => [
        ...p,
        "[ERROR] > Cannot upload image. Neural Tether is disconnected.",
      ]);
      return;
    }
    setIsAnalyzingImage(true);
    setLogs((p) => [
      ...p,
      `[VISION] > Processing image '${file.name}' for multi-modal hardware diagnostics...`,
    ]);
    const reader = new FileReader();
    reader.onload = (e) => {
      const base64String = e.target?.result as string;
      ws.send(
        JSON.stringify({
          command: "diagnostics_upload",
          image_data: base64String,
        })
      );
    };
    reader.readAsDataURL(file);
  };

  const fetchCheckpointHistory = () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setLogs((p) => [...p, "[ERROR] > Neural Tether is disconnected."]);
      return;
    }
    ws.send(JSON.stringify({ command: "get_history" }));
    setShowTimelineModal(true);
  };

  const rollbackToCheckpoint = (checkpointId: string) => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setLogs((p) => [...p, "[ERROR] > Neural Tether is disconnected."]);
      return;
    }
    ws.send(
      JSON.stringify({ command: "rollback", checkpoint_id: checkpointId })
    );
    setGuardrailPayload(null);
    setActiveNode(null);
    setShowTimelineModal(false);
  };

  const handleFileUpload = async (
    event: React.ChangeEvent<HTMLInputElement>
  ) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setIsUploading(true);
    setLogs((p) => [
      ...p,
      `[SYSTEM] > Initiating uplink for ${file.name}...`,
    ]);
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
        setLogs((p) => [...p, `[SUCCESS] > ${data.message}`]);
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(
            JSON.stringify({
              command: "chat",
              text: `I just uploaded a new dataset named ${file.name}. List all the tables inside it.`,
            })
          );
        }
      } else {
        setLogs((p) => [...p, `[ERROR] > ${data.message}`]);
      }
    } catch {
      setLogs((p) => [...p, "[ERROR] > Datacore uplink failed."]);
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleLiveDbConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!liveDbUri.trim()) return;
    setIsLinking(true);
    setLogs((p) => [
      ...p,
      "[SYSTEM] > Establishing secure tunnel to live database...",
    ]);
    try {
      const response = await fetch("http://localhost:8000/connect-live-db", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ connection_string: liveDbUri }),
      });
      const data = await response.json();
      if (data.status === "success") {
        setActiveDbName(
          "LIVE: " +
            (liveDbUri.split("@")[1]?.split("/")[0] || "Remote Node")
        );
        setLogs((p) => [...p, `[SUCCESS] > ${data.message}`]);
        setShowLiveDbModal(false);
        setLiveDbUri("");
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(
            JSON.stringify({
              command: "chat",
              text: "I just connected a live database. Please map the schema and tell me what tables we have.",
            })
          );
        }
      } else {
        setLogs((p) => [...p, `[ERROR] > ${data.message}`]);
      }
    } catch {
      setLogs((p) => [
        ...p,
        "[ERROR] > Live tether failed. Check network routing.",
      ]);
    } finally {
      setIsLinking(false);
    }
  };

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    if (chatInput.trim() && ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ command: "chat", text: chatInput }));
      setChatLog((prev) => [...prev, { role: "User", content: chatInput }]);
      setChatInput("");
    }
  };

  // --- RENDER ---
  return (
    <div className="w-screen h-screen bg-[#020202] text-gray-300 overflow-hidden flex flex-col selection:bg-cyan-500/30">
      {/* OMNI-HEADER */}
      <OmniHeader
        systemStatus={systemStatus}
        activeDbName={activeDbName}
        isUploading={isUploading}
        isAnalyzingImage={isAnalyzingImage}
        userRole={userRole}
        fileInputRef={fileInputRef}
        imageInputRef={imageInputRef}
        onFileUpload={handleFileUpload}
        onImageUpload={handleImageUpload}
        onMountFileClick={() => fileInputRef.current?.click()}
        onLiveUplinkClick={() => setShowLiveDbModal(true)}
        onTimeTravelClick={fetchCheckpointHistory}
        onHardwareVisionClick={() => imageInputRef.current?.click()}
        onCoreScanClick={triggerScan}
        onRoleChange={setUserRole}
      />

      {/* MAIN DASHBOARD */}
      <motion.main
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.6, delay: 0.15 }}
        className="flex-1 grid grid-cols-12 gap-4 p-4 overflow-hidden"
      >
        {/* LEFT COLUMN (8 cols) */}
        <div className="col-span-8 flex flex-col gap-4 overflow-hidden">
          {/* Metrics Row */}
          <MetricsRow
            systemStatus={systemStatus}
            guardrailPayload={guardrailPayload}
          />

          {/* Neural Flow Graph + Execution Feed */}
          <div className="flex-1 grid grid-rows-2 gap-4 overflow-hidden">
            {/* React Flow Neural Graph */}
            <div className="min-h-0">
              <NeuralFlowGraph activeNode={activeNode} />
            </div>

            {/* Execution Feed */}
            <div className="min-h-0 overflow-hidden">
              <ExecutionFeed
                logs={logs}
                guardrailPayload={guardrailPayload}
                blastRadiusData={blastRadiusData}
                visionFinding={visionFinding}
                userRole={userRole}
                onApprove={approveExecution}
                onAbort={() => setGuardrailPayload(null)}
              />
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN: Copilot (4 cols) */}
        <div className="col-span-4 overflow-hidden">
          <CopilotPanel
            chatLog={chatLog}
            chatInput={chatInput}
            onChatInputChange={setChatInput}
            onSendMessage={handleSendMessage}
            isConnected={systemStatus === "ONLINE"}
          />
        </div>
      </motion.main>

      {/* MODALS */}
      <LiveDbModal
        show={showLiveDbModal}
        liveDbUri={liveDbUri}
        isLinking={isLinking}
        onClose={() => setShowLiveDbModal(false)}
        onUriChange={setLiveDbUri}
        onSubmit={handleLiveDbConnect}
      />

      <TimelineModal
        show={showTimelineModal}
        history={checkpointHistory}
        onClose={() => setShowTimelineModal(false)}
        onRollback={rollbackToCheckpoint}
      />

      <SecurityAlertModal
        alert={securityAlert}
        onDismiss={() => {
          setSecurityAlert(null);
          setSystemStatus("ONLINE");
        }}
      />
    </div>
  );
}