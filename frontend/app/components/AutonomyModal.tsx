'use client'

import React, { useState, useEffect } from 'react'
import {
  ShieldCheck,
  X,
  Lock,
  CheckCircle2,
  AlertTriangle,
  Clock,
  Layers,
  FileCheck,
  Eye,
  Sliders,
  AlertOctagon,
  RefreshCw,
  Search
} from 'lucide-react'

interface AutonomyLevelInfo {
  level: number
  name: string
  title: string
  status: 'AVAILABLE' | 'RESTRICTED' | 'REQUIRES_REVIEW' | 'DISABLED' | 'NOT_IMPLEMENTED'
  description: string
  is_operational: boolean
}

interface AutonomyGrant {
  grant_id: string
  subject_type: string
  subject_id: string
  autonomy_level: number
  tenant_id: string
  workspace_id: string
  plant_id?: string
  data_mode: string
  status: 'ACTIVE' | 'SUSPENDED' | 'REVOKED' | 'EXPIRED'
  revision: number
  permitted_capabilities: string[]
  restricted_capabilities: string[]
  effective_from: number
  expires_at?: number
  created_by: string
}

interface CapabilityDef {
  capability_id: string
  name: string
  minimum_level: number
  description: string
  is_implemented: boolean
  is_execution: boolean
  requires_human_approval: boolean
}

interface AutonomyDecision {
  decision_id: string
  decision: 'ALLOW' | 'DENY' | 'REQUIRES_REVIEW' | 'NOT_IMPLEMENTED'
  reason_code: string
  reason: string
  subject_id: string
  requested_capability: string
  effective_autonomy_level: number
  data_mode: string
  risk_status: string
  approval_requirement: boolean
  evaluated_at: number
  decision_hash: string
}

interface AutonomyModalProps {
  isOpen: boolean
  onClose: () => void
}

export default function AutonomyModal({ isOpen, onClose }: AutonomyModalProps) {
  const [activeTab, setActiveTab] = useState<'levels' | 'grants' | 'capabilities' | 'decisions'>('levels')
  const [levels, setLevels] = useState<AutonomyLevelInfo[]>([])
  const [grants, setGrants] = useState<AutonomyGrant[]>([])
  const [capabilities, setCapabilities] = useState<CapabilityDef[]>([])
  const [decisions, setDecisions] = useState<AutonomyDecision[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = async () => {
    setLoading(true)
    setError(null)
    try {
      const headers = { 'Authorization': 'Bearer dev_admin_token' }

      const [levelsRes, grantsRes, capsRes, decsRes] = await Promise.all([
        fetch('http://localhost:8000/api/v3/autonomy/levels', { headers }),
        fetch('http://localhost:8000/api/v3/autonomy/grants?limit=20', { headers }),
        fetch('http://localhost:8000/api/v3/autonomy/capabilities', { headers }),
        fetch('http://localhost:8000/api/v3/autonomy/decisions?limit=20', { headers })
      ])

      if (levelsRes.ok) {
        setLevels(await levelsRes.json())
      }
      if (grantsRes.ok) {
        const gData = await grantsRes.json()
        setGrants(gData.grants || [])
      }
      if (capsRes.ok) {
        setCapabilities(await capsRes.json())
      }
      if (decsRes.ok) {
        setDecisions(await decsRes.json())
      }
    } catch (err) {
      console.error('Failed to load autonomy data:', err)
      setError('Failed to connect to Autonomy Governance service. Backend may be offline.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (isOpen) {
      fetchData()
    }
  }, [isOpen])

  if (!isOpen) return null

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'AVAILABLE':
        return <span className="px-2 py-0.5 rounded text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">AVAILABLE</span>
      case 'RESTRICTED':
        return <span className="px-2 py-0.5 rounded text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">RESTRICTED</span>
      case 'REQUIRES_REVIEW':
        return <span className="px-2 py-0.5 rounded text-xs font-semibold bg-yellow-500/10 text-yellow-400 border border-yellow-500/20">REQUIRES REVIEW</span>
      case 'DISABLED':
        return <span className="px-2 py-0.5 rounded text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">DISABLED</span>
      case 'NOT_IMPLEMENTED':
        return <span className="px-2 py-0.5 rounded text-xs font-semibold bg-zinc-700/30 text-zinc-400 border border-zinc-700">NOT IMPLEMENTED</span>
      case 'ACTIVE':
        return <span className="px-2 py-0.5 rounded text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">ACTIVE</span>
      case 'SUSPENDED':
        return <span className="px-2 py-0.5 rounded text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">SUSPENDED</span>
      case 'REVOKED':
        return <span className="px-2 py-0.5 rounded text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">REVOKED</span>
      case 'EXPIRED':
        return <span className="px-2 py-0.5 rounded text-xs font-semibold bg-zinc-700/30 text-zinc-400 border border-zinc-700">EXPIRED</span>
      case 'ALLOW':
        return <span className="px-2 py-0.5 rounded text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">ALLOW</span>
      case 'DENY':
        return <span className="px-2 py-0.5 rounded text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">DENY</span>
      default:
        return <span className="px-2 py-0.5 rounded text-xs font-semibold bg-zinc-800 text-zinc-300">{status}</span>
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-md">
      <div className="w-full max-w-6xl bg-zinc-950 border border-zinc-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col h-[88vh]">
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-800/80 bg-zinc-900/60">
          <div className="flex items-center space-x-3">
            <div className="p-2.5 bg-cyan-500/10 border border-cyan-500/20 rounded-xl">
              <ShieldCheck className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <h2 className="text-xl font-bold text-zinc-100">Autonomy Levels & Guarded Delegation</h2>
                <span className="text-xs px-2 py-0.5 bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 rounded font-mono">
                  Prompt 38
                </span>
              </div>
              <p className="text-xs text-zinc-400 font-mono mt-0.5">
                Deterministic Authority Boundaries • Execution Gateway Boundary Guard
              </p>
            </div>
          </div>
          <div className="flex items-center space-x-2">
            <button
              onClick={fetchData}
              disabled={loading}
              className="p-2 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 rounded-lg transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <button
              onClick={onClose}
              className="p-2 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 rounded-lg transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Invariant Banner */}
        <div className="px-6 py-3 bg-cyan-950/20 border-b border-cyan-800/30 flex items-center justify-between text-xs">
          <div className="flex items-center space-x-2 text-cyan-200">
            <Lock className="w-4 h-4 text-cyan-400 flex-shrink-0" />
            <span>
              <strong>Cardinal Invariant:</strong> An agent&apos;s ability to reason does <em>not</em> grant it operational authority.
              Level 4 &amp; 5 operational execution endpoints remain strictly <strong>DISABLED / UNIMPLEMENTED</strong>.
            </span>
          </div>
          <span className="text-cyan-400 font-mono text-[10px] uppercase tracking-wider px-2 py-0.5 bg-cyan-900/40 rounded border border-cyan-700/40">
            Fail-Closed Enforced
          </span>
        </div>

        {/* Navigation Tabs */}
        <div className="flex border-b border-zinc-800 px-6 bg-zinc-900/30">
          <button
            onClick={() => setActiveTab('levels')}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors flex items-center space-x-2 ${
              activeTab === 'levels'
                ? 'border-cyan-500 text-cyan-400'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Layers className="w-4 h-4" />
            <span>Autonomy Levels (0–5)</span>
          </button>
          <button
            onClick={() => setActiveTab('grants')}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors flex items-center space-x-2 ${
              activeTab === 'grants'
                ? 'border-cyan-500 text-cyan-400'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <FileCheck className="w-4 h-4" />
            <span>Active Grants ({grants.length})</span>
          </button>
          <button
            onClick={() => setActiveTab('capabilities')}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors flex items-center space-x-2 ${
              activeTab === 'capabilities'
                ? 'border-cyan-500 text-cyan-400'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Sliders className="w-4 h-4" />
            <span>Capability Registry ({capabilities.length})</span>
          </button>
          <button
            onClick={() => setActiveTab('decisions')}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors flex items-center space-x-2 ${
              activeTab === 'decisions'
                ? 'border-cyan-500 text-cyan-400'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Clock className="w-4 h-4" />
            <span>Decision Ledger ({decisions.length})</span>
          </button>
        </div>

        {/* Tab Content */}
        <div className="flex-1 overflow-y-auto p-6 bg-zinc-950">
          {error && (
            <div className="mb-4 p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-sm flex items-center space-x-3">
              <AlertTriangle className="w-5 h-5 text-rose-400 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {loading ? (
            <div className="flex flex-col items-center justify-center h-64 space-y-3">
              <RefreshCw className="w-8 h-8 text-cyan-500 animate-spin" />
              <p className="text-zinc-400 text-sm font-mono">Querying Autonomy Governance Engine...</p>
            </div>
          ) : (
            <>
              {/* TAB 1: LEVELS */}
              {activeTab === 'levels' && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {levels.map((lvl) => {
                    const isLocked = !lvl.is_operational
                    return (
                      <div
                        key={lvl.level}
                        className={`p-5 rounded-xl border flex flex-col justify-between transition-all ${
                          isLocked
                            ? 'bg-zinc-900/20 border-zinc-800/50 opacity-75'
                            : 'bg-zinc-900/60 border-zinc-800 hover:border-zinc-700'
                        }`}
                      >
                        <div>
                          <div className="flex items-center justify-between mb-3">
                            <span className="text-xs font-mono font-bold text-zinc-400">
                              LEVEL {lvl.level}
                            </span>
                            {getStatusBadge(lvl.status)}
                          </div>
                          <h3 className="text-base font-bold text-zinc-100 flex items-center space-x-2">
                            {isLocked && <Lock className="w-4 h-4 text-rose-400" />}
                            <span>{lvl.title.split('—')[1] || lvl.title}</span>
                          </h3>
                          <p className="text-xs text-zinc-400 mt-2 leading-relaxed">
                            {lvl.description}
                          </p>
                        </div>
                        <div className="mt-4 pt-3 border-t border-zinc-800/60 flex items-center justify-between text-[11px] font-mono">
                          <span className="text-zinc-500">Execution Authority:</span>
                          <span className={isLocked ? 'text-rose-400 font-semibold' : 'text-zinc-400'}>
                            {isLocked ? 'PROHIBITED (NONE)' : 'NON-MUTATING'}
                          </span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}

              {/* TAB 2: GRANTS */}
              {activeTab === 'grants' && (
                <div className="space-y-4">
                  {grants.length === 0 ? (
                    <div className="p-12 text-center border border-dashed border-zinc-800 rounded-2xl">
                      <FileCheck className="w-10 h-10 text-zinc-600 mx-auto mb-3" />
                      <p className="text-zinc-300 font-medium">No active autonomy grants found.</p>
                      <p className="text-xs text-zinc-500 mt-1">Grants can be provisioned by Security Administrators or Plant Managers.</p>
                    </div>
                  ) : (
                    grants.map((grant) => (
                      <div key={grant.grant_id} className="p-5 rounded-xl bg-zinc-900/60 border border-zinc-800">
                        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-800/60 pb-3 mb-3">
                          <div className="flex items-center space-x-3">
                            <span className="text-xs font-mono px-2 py-0.5 bg-zinc-800 text-zinc-300 rounded">
                              {grant.grant_id}
                            </span>
                            <span className="text-sm font-bold text-zinc-100">
                              Subject: {grant.subject_type} / {grant.subject_id}
                            </span>
                            {getStatusBadge(grant.status)}
                          </div>
                          <div className="flex items-center space-x-3 text-xs font-mono text-zinc-400">
                            <span>Rev {grant.revision}</span>
                            <span>Mode: <strong className="text-zinc-200">{grant.data_mode}</strong></span>
                            <span>Level: <strong className="text-cyan-400">Level {grant.autonomy_level}</strong></span>
                          </div>
                        </div>

                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs mb-3">
                          <div>
                            <span className="text-zinc-500 block">Tenant:</span>
                            <span className="font-mono text-zinc-300">{grant.tenant_id}</span>
                          </div>
                          <div>
                            <span className="text-zinc-500 block">Workspace:</span>
                            <span className="font-mono text-zinc-300">{grant.workspace_id}</span>
                          </div>
                          <div>
                            <span className="text-zinc-500 block">Plant Scope:</span>
                            <span className="font-mono text-zinc-300">{grant.plant_id || 'All Assigned (*) '}</span>
                          </div>
                          <div>
                            <span className="text-zinc-500 block">Expires:</span>
                            <span className="font-mono text-zinc-300">
                              {grant.expires_at ? new Date(grant.expires_at * 1000).toLocaleString() : 'No Expiry'}
                            </span>
                          </div>
                        </div>

                        {grant.permitted_capabilities.length > 0 && (
                          <div className="text-xs mt-2">
                            <span className="text-zinc-500 block mb-1">Permitted Capabilities:</span>
                            <div className="flex flex-wrap gap-1.5">
                              {grant.permitted_capabilities.map((c) => (
                                <span key={c} className="px-2 py-0.5 bg-cyan-950/40 text-cyan-300 border border-cyan-800/40 rounded text-[11px] font-mono">
                                  {c}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              )}

              {/* TAB 3: CAPABILITY REGISTRY */}
              {activeTab === 'capabilities' && (
                <div className="border border-zinc-800 rounded-xl overflow-hidden">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-zinc-900/80 text-zinc-400 font-mono uppercase tracking-wider border-b border-zinc-800">
                      <tr>
                        <th className="px-4 py-3">Capability ID</th>
                        <th className="px-4 py-3">Name</th>
                        <th className="px-4 py-3">Min Level</th>
                        <th className="px-4 py-3">Status</th>
                        <th className="px-4 py-3">Approval Req</th>
                        <th className="px-4 py-3">Execution Boundary</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-800/60 font-mono">
                      {capabilities.map((cap) => (
                        <tr key={cap.capability_id} className="hover:bg-zinc-900/30">
                          <td className="px-4 py-3 font-semibold text-zinc-200">{cap.capability_id}</td>
                          <td className="px-4 py-3 text-zinc-300">{cap.name}</td>
                          <td className="px-4 py-3 text-cyan-400">Level {cap.minimum_level}</td>
                          <td className="px-4 py-3">
                            {cap.is_implemented ? (
                              <span className="text-emerald-400">IMPLEMENTED</span>
                            ) : (
                              <span className="text-rose-400">DISABLED</span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-zinc-400">
                            {cap.requires_human_approval ? (
                              <span className="text-amber-400">YES (HITL)</span>
                            ) : (
                              'NO'
                            )}
                          </td>
                          <td className="px-4 py-3">
                            {cap.is_execution ? (
                              <span className="text-rose-400 font-bold">MUTATING (BLOCKED)</span>
                            ) : (
                              <span className="text-zinc-500">READ / PROPOSE ONLY</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* TAB 4: DECISION LEDGER */}
              {activeTab === 'decisions' && (
                <div className="space-y-3">
                  {decisions.length === 0 ? (
                    <div className="p-12 text-center border border-dashed border-zinc-800 rounded-2xl">
                      <Clock className="w-10 h-10 text-zinc-600 mx-auto mb-3" />
                      <p className="text-zinc-300 font-medium">No evaluation decisions recorded in current session.</p>
                      <p className="text-xs text-zinc-500 mt-1">Evaluations occur deterministically when agents request capabilities.</p>
                    </div>
                  ) : (
                    decisions.map((dec) => (
                      <div key={dec.decision_id} className="p-4 rounded-xl bg-zinc-900/50 border border-zinc-800 text-xs">
                        <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                          <div className="flex items-center space-x-2">
                            {getStatusBadge(dec.decision)}
                            <span className="font-mono font-bold text-zinc-200">{dec.requested_capability}</span>
                            <span className="text-zinc-500">for</span>
                            <span className="font-mono text-zinc-300">{dec.subject_id}</span>
                          </div>
                          <div className="flex items-center space-x-3 text-zinc-400 font-mono text-[11px]">
                            <span>Reason: <strong className="text-zinc-200">{dec.reason_code}</strong></span>
                            <span>{new Date(dec.evaluated_at * 1000).toLocaleTimeString()}</span>
                          </div>
                        </div>
                        <p className="text-zinc-300 mb-2 font-sans">{dec.reason}</p>
                        <div className="pt-2 border-t border-zinc-800/40 flex items-center justify-between text-[10px] font-mono text-zinc-500">
                          <span>SHA-256 Decision Hash: {dec.decision_hash.slice(0, 16)}...</span>
                          <span>Risk: {dec.risk_status} | Approval Req: {dec.approval_requirement ? 'YES' : 'NO'}</span>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-zinc-800 bg-zinc-900/40 flex items-center justify-between text-xs text-zinc-400">
          <span>Autonomy Governance Architecture • Prompt 38 Baseline</span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 font-medium transition-colors"
          >
            Close
          </button>
        </div>

      </div>
    </div>
  )
}
