"use client";

import React, { useState, useEffect } from "react";
import { format } from "date-fns";
import { fetchSage } from "../../lib/api";
export function IncidentModal({ onClose }: { onClose: () => void }) {
  const [incidents, setIncidents] = useState<any[]>([]);
  const [selectedIncident, setSelectedIncident] = useState<any>(null);
  const [incidentDetails, setIncidentDetails] = useState<any>(null);
  const [loadingDetails, setLoadingDetails] = useState(false);

  useEffect(() => {
    async function loadIncidents() {
      try {
        const res = await fetchSage("/api/v3/incidents");
        setIncidents(res);
      } catch (err) {
        console.error("Failed to load Incidents", err);
      }
    }
    loadIncidents();
    const interval = setInterval(loadIncidents, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleSelectIncident = async (incident: any) => {
    setSelectedIncident(incident);
    setLoadingDetails(true);
    try {
      const details = await fetchSage(`/api/v3/incidents/${incident.incident_id}`);
      setIncidentDetails(details);
    } catch (err) {
      console.error("Failed to load Incident details", err);
    } finally {
      setLoadingDetails(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-sage-900 border border-sage-700 rounded-xl shadow-2xl w-full max-w-7xl max-h-[90vh] overflow-hidden flex flex-col text-sage-100">
        
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-sage-800 bg-sage-900/50">
          <div>
            <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-red-400 to-orange-300">
              Incident Management
            </h2>
            <p className="text-sm text-sage-400 mt-1">
              Read-only inspection of operational incidents, timelines, and associations.
            </p>
          </div>
          <button onClick={onClose} className="text-sage-400 hover:text-white transition-colors">
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-hidden flex">
          {/* List Pane */}
          <div className="w-1/3 border-r border-sage-800 bg-sage-900/30 flex flex-col">
            <div className="p-4 border-b border-sage-800 flex justify-between items-center bg-sage-800/50">
              <span className="font-semibold text-white tracking-wide">Active Incidents</span>
              <span className="px-2 py-1 bg-sage-700 text-white text-xs rounded">{incidents.length}</span>
            </div>
            <div className="flex-1 overflow-y-auto p-2 scrollbar-thin">
              {incidents.map((inc) => (
                <div 
                  key={inc.incident_id} 
                  onClick={() => handleSelectIncident(inc)}
                  className={`p-4 mb-2 rounded cursor-pointer border transition-colors ${selectedIncident?.incident_id === inc.incident_id ? 'border-orange-500 bg-sage-800' : 'border-sage-700 hover:border-sage-500 bg-sage-900/50'}`}
                >
                  <div className="flex justify-between items-start mb-2">
                    <span className="text-xs font-mono text-sage-400 truncate w-32">{inc.incident_id}</span>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${inc.status === 'CLOSED' ? 'bg-sage-700 text-white' : 'bg-yellow-900 text-yellow-300'}`}>{inc.status}</span>
                  </div>
                  <h3 className="text-sm font-semibold text-white mb-2">{inc.title}</h3>
                  <div className="flex justify-between text-xs text-sage-500">
                    <span className={`px-2 py-0.5 rounded ${inc.severity === 'CRITICAL' ? 'bg-red-900 text-red-200' : 'bg-sage-800'}`}>
                      {inc.severity}
                    </span>
                    <span>{format(new Date(inc.updated_at), "MMM d, HH:mm")}</span>
                  </div>
                </div>
              ))}
              {incidents.length === 0 && (
                <div className="p-6 text-center text-sage-500 text-sm">
                  No incidents recorded.
                </div>
              )}
            </div>
          </div>

          {/* Details Pane */}
          <div className="w-2/3 flex flex-col bg-sage-900">
            {selectedIncident ? (
              loadingDetails ? (
                <div className="flex-1 flex items-center justify-center text-sage-500">
                  Loading incident data...
                </div>
              ) : incidentDetails ? (
                <div className="flex-1 p-6 overflow-y-auto">
                  <div className="space-y-6">
                    
                    {/* Header Info */}
                    <div className="border-b border-sage-800 pb-4">
                      <div className="flex justify-between items-start mb-2">
                        <h2 className="text-xl font-bold text-white">{incidentDetails.incident.title}</h2>
                        <span className="px-2 py-1 rounded text-xs font-medium border border-sage-600 bg-transparent text-sage-300">{incidentDetails.incident.category}</span>
                      </div>
                      <p className="text-sage-400 text-sm">{incidentDetails.incident.description || "No description provided."}</p>
                    </div>

                    {/* Metadata Grid */}
                    <div className="grid grid-cols-4 gap-4">
                      <div className="bg-sage-800/50 p-3 rounded border border-sage-700">
                        <span className="block text-[10px] uppercase tracking-wider text-sage-500 mb-1">Status</span>
                        <span className="text-sm font-semibold text-orange-400">{incidentDetails.incident.status}</span>
                      </div>
                      <div className="bg-sage-800/50 p-3 rounded border border-sage-700">
                        <span className="block text-[10px] uppercase tracking-wider text-sage-500 mb-1">Severity</span>
                        <span className="text-sm font-semibold">{incidentDetails.incident.severity}</span>
                      </div>
                      <div className="bg-sage-800/50 p-3 rounded border border-sage-700">
                        <span className="block text-[10px] uppercase tracking-wider text-sage-500 mb-1">Priority</span>
                        <span className="text-sm font-semibold">{incidentDetails.incident.priority}</span>
                      </div>
                      <div className="bg-sage-800/50 p-3 rounded border border-sage-700">
                        <span className="block text-[10px] uppercase tracking-wider text-sage-500 mb-1">Assigned</span>
                        <span className="text-sm font-semibold text-blue-300">{incidentDetails.incident.assigned_user || "Unassigned"}</span>
                      </div>
                    </div>

                    {/* Timeline & Evidence */}
                    <div className="grid grid-cols-2 gap-6">
                      
                      {/* Timeline */}
                      <div className="bg-sage-800/30 rounded border border-sage-700 p-4">
                        <h3 className="text-sm font-semibold text-white mb-4">Activity Timeline</h3>
                        <div className="space-y-3">
                          {incidentDetails.timeline.map((entry: any) => (
                            <div key={entry.entry_id} className="text-xs flex gap-3 border-l-2 border-sage-700 pl-3">
                              <div className="w-16 shrink-0 text-sage-500 font-mono">
                                {format(new Date(entry.timestamp), "HH:mm:ss")}
                              </div>
                              <div>
                                <span className="font-semibold text-sage-300">{entry.entry_type}</span>
                                <span className="text-sage-500 ml-2">by {entry.actor}</span>
                                {entry.metadata && Object.keys(entry.metadata).length > 0 && (
                                  <pre className="mt-1 text-[10px] text-sage-400 bg-sage-900 p-1 rounded">
                                    {JSON.stringify(entry.metadata, null, 2)}
                                  </pre>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Evidence & Events */}
                      <div className="space-y-6">
                        <div className="bg-sage-800/30 rounded border border-sage-700 p-4">
                          <h3 className="text-sm font-semibold text-white mb-4">Associated Events</h3>
                          {incidentDetails.events.length === 0 ? (
                            <span className="text-xs text-sage-500">No associated events.</span>
                          ) : (
                            <div className="space-y-2">
                              {incidentDetails.events.map((evt: any) => (
                                <div key={evt.event_id} className="bg-sage-800 p-2 rounded text-xs font-mono text-sage-300 flex justify-between">
                                  <span>{evt.event_id.substring(0,12)}...</span>
                                  <span className="text-[9px] border border-sage-600 px-1 py-0.5 rounded uppercase">{evt.relationship_type}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>

                        <div className="bg-sage-800/30 rounded border border-sage-700 p-4">
                          <h3 className="text-sm font-semibold text-white mb-4">Evidence Records</h3>
                          {incidentDetails.evidence.length === 0 ? (
                            <span className="text-xs text-sage-500">No evidence attached.</span>
                          ) : (
                            <div className="space-y-2">
                              {incidentDetails.evidence.map((evid: any) => (
                                <div key={evid.evidence_id} className="bg-sage-800 p-2 rounded text-xs">
                                  <div className="flex justify-between font-mono mb-1">
                                    <span className="text-blue-300">{evid.evidence_type}</span>
                                    <span className="text-sage-500">{format(new Date(evid.timestamp), "HH:mm")}</span>
                                  </div>
                                  <div className="text-sage-400 truncate">{evid.source_id}</div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>

                    </div>
                  </div>
                </div>
              ) : (
                <div className="flex-1 flex items-center justify-center text-red-400">
                  Failed to load incident details.
                </div>
              )
            ) : (
              <div className="flex-1 flex items-center justify-center text-sage-500">
                Select an incident from the list to view details.
              </div>
            )}
          </div>
        </div>
        
      </div>
    </div>
  );
}
