"use client";
import React, { useMemo } from "react";
import ReactFlow, { Background, Node, Edge } from "reactflow";
import "reactflow/dist/style.css";
import NeuralNode from "./NeuralNode";
import AnimatedEdge from "./AnimatedEdge";

interface NeuralFlowGraphProps {
  activeNode: string | null;
}

const nodeTypes = { neuralNode: NeuralNode };
const edgeTypes = { animatedEdge: AnimatedEdge };

// Agent topology positions (hand-tuned for dashboard layout)
const baseNodes: Node[] = [
  {
    id: "security_agent",
    type: "neuralNode",
    position: { x: 280, y: 0 },
    data: { label: "Security Agent", icon: "🛡️", isActive: false, variant: "threat" },
  },
  {
    id: "discovery",
    type: "neuralNode",
    position: { x: 60, y: 120 },
    data: { label: "Discovery", icon: "🔍", isActive: false, variant: "default" },
  },
  {
    id: "copilot_agent",
    type: "neuralNode",
    position: { x: 500, y: 120 },
    data: { label: "Copilot", icon: "🧠", isActive: false, variant: "default" },
  },
  {
    id: "risk_agent",
    type: "neuralNode",
    position: { x: 60, y: 240 },
    data: { label: "Risk Agent", icon: "⚡", isActive: false, variant: "warning" },
  },
  {
    id: "supervisor",
    type: "neuralNode",
    position: { x: 280, y: 240 },
    data: { label: "Supervisor", icon: "📡", isActive: false, variant: "default" },
  },
  {
    id: "strategy_worker",
    type: "neuralNode",
    position: { x: 60, y: 370 },
    data: { label: "Strategy", icon: "♟️", isActive: false, variant: "default" },
  },
  {
    id: "web_researcher",
    type: "neuralNode",
    position: { x: 280, y: 370 },
    data: { label: "Web Research", icon: "🌐", isActive: false, variant: "default" },
  },
  {
    id: "evaluator",
    type: "neuralNode",
    position: { x: 500, y: 370 },
    data: { label: "Evaluator", icon: "⚖️", isActive: false, variant: "default" },
  },
  {
    id: "execution",
    type: "neuralNode",
    position: { x: 280, y: 500 },
    data: { label: "Execution", icon: "🚀", isActive: false, variant: "success" },
  },
];

const baseEdges: Edge[] = [
  // Security gate
  { id: "e-sec-disc", source: "security_agent", target: "discovery", type: "animatedEdge", data: { isActive: false } },
  { id: "e-sec-cop", source: "security_agent", target: "copilot_agent", type: "animatedEdge", data: { isActive: false } },
  // Discovery pipeline
  { id: "e-disc-risk", source: "discovery", target: "risk_agent", type: "animatedEdge", data: { isActive: false } },
  { id: "e-risk-sup", source: "risk_agent", target: "supervisor", type: "animatedEdge", data: { isActive: false } },
  // Supervisor routing
  { id: "e-sup-strat", source: "supervisor", target: "strategy_worker", type: "animatedEdge", data: { isActive: false } },
  { id: "e-sup-web", source: "supervisor", target: "web_researcher", type: "animatedEdge", data: { isActive: false } },
  { id: "e-sup-eval", source: "supervisor", target: "evaluator", type: "animatedEdge", data: { isActive: false } },
  // Worker feedback loops
  { id: "e-strat-sup", source: "strategy_worker", target: "supervisor", type: "animatedEdge", data: { isActive: false } },
  { id: "e-web-sup", source: "web_researcher", target: "supervisor", type: "animatedEdge", data: { isActive: false } },
  { id: "e-eval-sup", source: "evaluator", target: "supervisor", type: "animatedEdge", data: { isActive: false } },
  // Execution
  { id: "e-sup-exec", source: "supervisor", target: "execution", type: "animatedEdge", data: { isActive: false } },
];

// Map: when a node is active, which edges should glow
const activeEdgeMap: Record<string, string[]> = {
  security_agent: ["e-sec-disc", "e-sec-cop"],
  discovery: ["e-disc-risk"],
  risk_agent: ["e-risk-sup"],
  copilot_agent: [],
  supervisor: ["e-sup-strat", "e-sup-web", "e-sup-eval", "e-sup-exec"],
  strategy_worker: ["e-strat-sup"],
  web_researcher: ["e-web-sup"],
  evaluator: ["e-eval-sup"],
  execution: [],
};

export default function NeuralFlowGraph({ activeNode }: NeuralFlowGraphProps) {
  const nodes = useMemo(() => {
    return baseNodes.map((node) => ({
      ...node,
      data: {
        ...node.data,
        isActive: activeNode === node.id,
      },
    }));
  }, [activeNode]);

  const edges = useMemo(() => {
    const activeEdgeIds = activeNode ? (activeEdgeMap[activeNode] || []) : [];
    return baseEdges.map((edge) => ({
      ...edge,
      data: {
        ...edge.data,
        isActive: activeEdgeIds.includes(edge.id),
      },
    }));
  }, [activeNode]);

  return (
    <div className="w-full h-full rounded-xl overflow-hidden bg-black/20 border border-white/[0.04]">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="rgba(255,255,255,0.02)" gap={24} size={1} />
      </ReactFlow>
    </div>
  );
}
