'use client'

import React, { useState, useEffect } from 'react'
import { FileText, X, AlertCircle, Clock, Hash, MapPin, Database, Tag } from 'lucide-react'

interface EventReferences {
  ontology_id?: string
  twin_id?: string
  kg_node_id?: string
  anomaly_id?: string
  source_system?: string
  source_record_id?: string
}

interface CanonicalEvent {
  event_id: string
  schema_version: string
  event_fingerprint: string
  tenant_id: string
  workspace_id: string
  plant_id: string
  category: string
  event_type: string
  severity: string
  lifecycle: string
  occurred_at: string
  observed_at: string
  recorded_at: string
  correlation_id?: string
  causation_id?: string
  provenance: string
  references: EventReferences
  payload: any
}

interface EventModalProps {
  isOpen: boolean
  onClose: () => void
}

export default function EventModal({ isOpen, onClose }: EventModalProps) {
  const [events, setEvents] = useState<CanonicalEvent[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (isOpen) {
      setLoading(true)
      fetch('http://localhost:8000/api/v3/events?limit=50', {
        headers: {
          'Authorization': 'Bearer dev_admin_token'
        }
      })
      .then(res => res.json())
      .then(data => {
        setEvents(data || [])
        setLoading(false)
      })
      .catch(err => {
        console.error('Failed to fetch events', err)
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
            <div className="p-2 bg-indigo-500/10 rounded-lg">
              <FileText className="w-5 h-5 text-indigo-400" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-zinc-100">Canonical Event Log</h2>
              <p className="text-sm text-zinc-400 font-mono mt-0.5">V3 Deterministic Immutability • Observational</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-zinc-800 rounded-lg transition-colors">
            <X className="w-5 h-5 text-zinc-400" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 bg-zinc-900">
          {/* Info Banner */}
          <div className="mb-6 flex items-start space-x-3 bg-indigo-500/10 border border-indigo-500/20 p-4 rounded-xl">
            <AlertCircle className="w-5 h-5 text-indigo-400 mt-0.5" />
            <div>
              <h3 className="text-sm font-semibold text-indigo-100">Immutable Ledger</h3>
              <p className="text-sm text-indigo-300/80 mt-1">
                Events represent deterministic occurrences within the enterprise environment. 
                They are deduplicated via cryptographic fingerprints and are strictly observational. 
                <strong className="text-indigo-200"> No execution handlers are tied directly to events.</strong>
              </p>
            </div>
          </div>

          {loading ? (
            <div className="flex items-center justify-center h-64">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500"></div>
            </div>
          ) : events.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 border-2 border-dashed border-zinc-800 rounded-xl">
              <FileText className="w-12 h-12 text-zinc-600 mb-3" />
              <p className="text-zinc-400">No canonical events recorded in this environment.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {events.map((evt) => (
                <div key={evt.event_id} className="border border-zinc-800 bg-zinc-800/20 rounded-xl p-5 hover:border-zinc-700 transition-all">
                  <div className="flex justify-between items-start mb-4">
                    <div className="flex items-center space-x-3">
                      <div className={`px-2.5 py-1 text-xs font-semibold rounded-md border ${
                        evt.severity === 'CRITICAL' ? 'bg-rose-500/10 text-rose-400 border-rose-500/20' :
                        evt.severity === 'HIGH' ? 'bg-orange-500/10 text-orange-400 border-orange-500/20' :
                        evt.severity === 'MEDIUM' ? 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20' :
                        evt.severity === 'LOW' ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' :
                        'bg-zinc-500/10 text-zinc-400 border-zinc-500/20'
                      }`}>
                        {evt.severity}
                      </div>
                      <h4 className="text-lg font-medium text-zinc-200">{evt.event_type}</h4>
                    </div>
                    <div className="text-right">
                      <div className="text-sm text-zinc-400 flex items-center justify-end space-x-1.5">
                        <Clock className="w-3.5 h-3.5" />
                        <span>{new Date(evt.occurred_at).toLocaleString()}</span>
                      </div>
                      <div className="text-xs text-zinc-500 mt-1 font-mono flex items-center justify-end space-x-1">
                        <Hash className="w-3 h-3" />
                        <span className="truncate w-32" title={evt.event_fingerprint}>
                          {evt.event_fingerprint.substring(0, 12)}...
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                    <div className="bg-zinc-800/50 p-3 rounded-lg border border-zinc-700/30">
                      <div className="flex items-center space-x-1.5 text-zinc-500 mb-1">
                        <MapPin className="w-3.5 h-3.5" />
                        <span className="text-xs font-medium uppercase tracking-wider">Scope</span>
                      </div>
                      <div className="text-sm text-zinc-300 font-mono truncate">
                        {evt.tenant_id} / {evt.plant_id}
                      </div>
                    </div>

                    <div className="bg-zinc-800/50 p-3 rounded-lg border border-zinc-700/30">
                      <div className="flex items-center space-x-1.5 text-zinc-500 mb-1">
                        <Tag className="w-3.5 h-3.5" />
                        <span className="text-xs font-medium uppercase tracking-wider">Category</span>
                      </div>
                      <div className="text-sm text-zinc-300 capitalize">
                        {evt.category.toLowerCase()}
                      </div>
                    </div>

                    <div className="bg-zinc-800/50 p-3 rounded-lg border border-zinc-700/30">
                      <div className="flex items-center space-x-1.5 text-zinc-500 mb-1">
                        <Database className="w-3.5 h-3.5" />
                        <span className="text-xs font-medium uppercase tracking-wider">Lifecycle</span>
                      </div>
                      <div className="text-sm text-zinc-300">
                        {evt.lifecycle}
                      </div>
                    </div>

                    <div className="bg-zinc-800/50 p-3 rounded-lg border border-zinc-700/30">
                      <div className="flex items-center space-x-1.5 text-zinc-500 mb-1">
                        <FileText className="w-3.5 h-3.5" />
                        <span className="text-xs font-medium uppercase tracking-wider">Provenance</span>
                      </div>
                      <div className="text-sm text-zinc-300 font-mono truncate">
                        {evt.provenance}
                      </div>
                    </div>
                  </div>

                  {evt.references && Object.keys(evt.references).some(k => evt.references[k as keyof EventReferences] !== null) && (
                    <div className="mt-4 pt-4 border-t border-zinc-800">
                      <h5 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">Linked References</h5>
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(evt.references).map(([key, val]) => {
                          if (!val) return null;
                          return (
                            <div key={key} className="px-2 py-1 bg-zinc-800 rounded border border-zinc-700 text-xs font-mono text-zinc-300 flex items-center space-x-1.5">
                              <span className="text-zinc-500">{key}:</span>
                              <span className="truncate max-w-[150px]">{val}</span>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {/* Optional Payload Inspector */}
                  <div className="mt-4 pt-4 border-t border-zinc-800">
                     <details className="group">
                        <summary className="text-xs font-semibold text-zinc-500 uppercase tracking-wider cursor-pointer hover:text-indigo-400 transition-colors">
                          View Raw Payload
                        </summary>
                        <div className="mt-3 p-3 bg-black/40 rounded-lg border border-zinc-800 overflow-x-auto">
                          <pre className="text-xs text-indigo-300/70 font-mono m-0">
                            {JSON.stringify(evt.payload, null, 2)}
                          </pre>
                        </div>
                     </details>
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
