"use client";
import React from "react";
import { getBezierPath, EdgeProps } from "reactflow";

export default function AnimatedEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  style = {},
}: EdgeProps) {
  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });

  const isActive = data?.isActive || false;
  const edgeColor = isActive ? "#22d3ee" : "#1a1a2e";
  const glowOpacity = isActive ? 0.6 : 0;

  return (
    <>
      {/* Glow underlay (wider, blurred) */}
      {isActive && (
        <path
          d={edgePath}
          fill="none"
          stroke="#22d3ee"
          strokeWidth={8}
          strokeOpacity={0.15}
          filter="blur(4px)"
          className="pointer-events-none"
        />
      )}

      {/* Base edge path */}
      <path
        id={id}
        d={edgePath}
        fill="none"
        stroke={edgeColor}
        strokeWidth={isActive ? 2.5 : 1.5}
        strokeLinecap="round"
        className="transition-all duration-500"
        style={style}
      />

      {/* Animated flowing dashes */}
      {isActive && (
        <path
          d={edgePath}
          fill="none"
          stroke="#22d3ee"
          strokeWidth={2}
          strokeLinecap="round"
          className="edge-animated-stream"
          strokeOpacity={0.9}
        />
      )}

      {/* Flowing particle dots */}
      {isActive && (
        <>
          <circle r="3" fill="#22d3ee" filter="url(#particleGlow)">
            <animateMotion
              dur="1.8s"
              repeatCount="indefinite"
              path={edgePath}
            />
          </circle>
          <circle r="2" fill="#67e8f9" opacity="0.6">
            <animateMotion
              dur="1.8s"
              repeatCount="indefinite"
              path={edgePath}
              begin="0.6s"
            />
          </circle>
          <circle r="1.5" fill="#a5f3fc" opacity="0.4">
            <animateMotion
              dur="1.8s"
              repeatCount="indefinite"
              path={edgePath}
              begin="1.2s"
            />
          </circle>
        </>
      )}

      {/* SVG filter for particle glow */}
      <defs>
        <filter id="particleGlow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
    </>
  );
}
