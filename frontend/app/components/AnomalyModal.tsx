'use client'

import React, { useState, useEffect } from 'react'
import { AlertTriangle, X, Activity, BarChart2, CheckCircle, ShieldAlert } from 'lucide-react'

interface AnomalyEvidence {
  source_timestamp: string
  metric: string
  value: string | number
  baseline_reference_id?: string
  data_quality_status: string
}

interface AnomalyDetection {
  anomaly_id: string
  entity_id: string
  metric: string
  type: string
  status: string
  severity: string
  detector_method: string
  anomaly_score?: number
  evidence: AnomalyEvidence[]
  first_detected_at: string
  last_detected_at: string
  occurrence_count: number
}

interface AnomalyModalProps {
  isOpen: boolean
  onClose: () => void
}

export default function AnomalyModal({ isOpen, onClose }: AnomalyModalProps) {
  const [anomalies, setAnomalies] = useState<AnomalyDetection[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (isOpen) {
      setLoading(true)
      fetch('http://localhost:8000/api/v3/anomalies?limit=50', {
        headers: {
          'Authorization': 'Bearer dev_admin_token'
        }
      })
      .then(res => res.json())
      .then(data => {
        setAnomalies(data.anomalies || [])
        setLoading(false)
      })
      .catch(err => {
        console.error('Failed to fetch anomalies', err)
        setLoading(false)
      })
    }
  }, [isOpen])

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-5xl bg-zinc-900 border border-zinc-700/50 rounded-2xl shadow-2xl overflow-hidden flex flex-col h-[85vh]">
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-800 bg-zinc-900/50">
          <div className="flex items-center space-x-3">
            <div className="p-2 bg-rose-500/10 rounded-lg">
              <Activity className="w-5 h-5 text-rose-400" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-zinc-100">Anomaly Detection Engine</h2>
              <p className="text-sm text-zinc-400 font-mono mt-0.5">V3 Observational Layer • Zero Mutations</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-zinc-800 rounded-lg transition-colors">
            <X className="w-5 h-5 text-zinc-400" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 bg-zinc-900">
          {/* Warning Banner */}
          <div className="mb-6 flex items-start space-x-3 bg-blue-500/10 border border-blue-500/20 p-4 rounded-xl">
            <ShieldAlert className="w-5 h-5 text-blue-400 mt-0.5" />
            <div>
              <h3 className="text-sm font-semibold text-blue-100">Observational Only</h3>
              <p className="text-sm text-blue-300/80 mt-1">
                The Anomaly Engine strictly identifies unusual mathematical observations. 
                <strong className="text-blue-200"> Anomaly detected ≠ Equipment failure. </strong>
                This module has zero execution privileges.
              </p>
            </div>
          </div>

          {loading ? (
            <div className="flex items-center justify-center h-64">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-rose-500"></div>
            </div>
          ) : anomalies.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 border-2 border-dashed border-zinc-800 rounded-xl">
              <CheckCircle className="w-12 h-12 text-emerald-500 mb-3" />
              <h3 className="text-lg font-medium text-zinc-300">No Anomalies Detected</h3>
              <p className="text-zinc-500 mt-1">All monitored metrics are operating within baseline limits.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {anomalies.map((anom) => (
                <div key={anom.anomaly_id} className="bg-zinc-800/50 border border-zinc-700/50 rounded-xl p-5 transition-all hover:bg-zinc-800">
                  <div className="flex justify-between items-start mb-4">
                    <div className="flex items-center space-x-3">
                      <div className={`p-2 rounded-lg ${
                        anom.severity === 'CRITICAL' ? 'bg-rose-500/20 text-rose-400' :
                        anom.severity === 'HIGH' ? 'bg-orange-500/20 text-orange-400' :
                        'bg-amber-500/20 text-amber-400'
                      }`}>
                        <AlertTriangle className="w-5 h-5" />
                      </div>
                      <div>
                        <div className="flex items-center space-x-2">
                          <h4 className="text-base font-semibold text-zinc-100">{anom.metric.toUpperCase()} Anomaly</h4>
                          <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-zinc-700 text-zinc-300">
                            {anom.type}
                          </span>
                        </div>
                        <p className="text-sm text-zinc-400 font-mono mt-1">Entity: {anom.entity_id}</p>
                      </div>
                    </div>
                    
                    <div className="text-right">
                      <div className="text-sm font-semibold text-zinc-200">
                        Score: {anom.anomaly_score?.toFixed(2) || 'N/A'}
                      </div>
                      <div className="text-xs text-zinc-500 font-mono mt-1">
                        {anom.detector_method}
                      </div>
                    </div>
                  </div>

                  {/* Evidence Blocks */}
                  <div className="grid grid-cols-2 gap-4 mt-4">
                    {anom.evidence.map((ev, idx) => (
                      <div key={idx} className="bg-zinc-900/50 p-3 rounded-lg border border-zinc-800">
                        <div className="flex justify-between text-xs mb-2">
                          <span className="text-zinc-500 font-mono">Value Observed</span>
                          <span className={`font-mono ${ev.data_quality_status === 'PASS' ? 'text-emerald-400' : 'text-rose-400'}`}>
                            DQ: {ev.data_quality_status}
                          </span>
                        </div>
                        <div className="text-xl font-bold text-zinc-200">
                          {String(ev.value)}
                        </div>
                        <div className="text-xs text-zinc-500 font-mono mt-2">
                          {new Date(ev.source_timestamp).toLocaleString()}
                        </div>
                      </div>
                    ))}
                    
                    {/* Lifecycle info */}
                    <div className="bg-zinc-900/50 p-3 rounded-lg border border-zinc-800 flex flex-col justify-center">
                      <div className="flex justify-between items-center text-xs mb-1">
                        <span className="text-zinc-500">Occurrences</span>
                        <span className="text-zinc-300 font-mono">{anom.occurrence_count}</span>
                      </div>
                      <div className="flex justify-between items-center text-xs mb-1">
                        <span className="text-zinc-500">First Detected</span>
                        <span className="text-zinc-300 font-mono truncate ml-2">
                          {new Date(anom.first_detected_at).toLocaleString()}
                        </span>
                      </div>
                      <div className="flex justify-between items-center text-xs">
                        <span className="text-zinc-500">Status</span>
                        <span className="text-zinc-300 font-mono">{anom.status}</span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
