"use client";

import React, { useState, useEffect } from 'react';
import api from '../../lib/api';

interface SLACustomerRiskModalProps {
  isOpen: boolean;
  onClose: () => void;
  customerId: string;
}

export default function SLACustomerRiskModal({ isOpen, onClose, customerId }: SLACustomerRiskModalProps) {
  const [loading, setLoading] = useState(false);
  const [assessments, setAssessments] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen && customerId) {
      fetchAssessments();
    }
  }, [isOpen, customerId]);

  const fetchAssessments = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getSLACustomerRiskSummary(customerId);
      setAssessments(data);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch SLA Customer Risk Data');
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-full max-w-5xl max-h-[90vh] overflow-hidden flex flex-col font-sans">
        
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-800 bg-slate-800/50">
          <div className="flex items-center space-x-3">
            <h2 className="text-xl font-semibold text-white tracking-wide">
              SLA &amp; Customer Risk Intelligence
            </h2>
            <span className="px-2 py-0.5 text-xs font-bold uppercase tracking-wider text-amber-500 bg-amber-500/10 border border-amber-500/20 rounded">
              ANALYTICAL ONLY
            </span>
          </div>
          <button 
            onClick={onClose}
            className="text-slate-400 hover:text-white transition-colors p-1"
          >
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {error && (
            <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
              {error}
            </div>
          )}

          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500"></div>
            </div>
          ) : assessments.length === 0 ? (
            <div className="text-center py-12 text-slate-400">
              No recent SLA risk assessments found for this customer.
            </div>
          ) : (
            <div className="space-y-8">
              {assessments.map((assessment) => (
                <div key={assessment.assessment_id} className="bg-slate-800/40 border border-slate-700/50 rounded-lg p-5 space-y-4">
                  
                  {/* Top line: Status & Confidence */}
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="text-xs text-slate-400 uppercase tracking-wider mb-1">Assessment ID</div>
                      <div className="text-sm font-mono text-slate-300">{assessment.assessment_id}</div>
                      <div className="text-xs text-slate-500 mt-1">{new Date(assessment.assessment_timestamp).toLocaleString()}</div>
                    </div>
                    <div className="flex space-x-4">
                      <div className="text-right">
                        <div className="text-xs text-slate-400 uppercase tracking-wider mb-1">Risk Level</div>
                        <div className={`text-lg font-bold ${assessment.risk_level === 'CRITICAL' ? 'text-red-500' : assessment.risk_level === 'HIGH' ? 'text-orange-500' : assessment.risk_level === 'MEDIUM' ? 'text-amber-500' : 'text-emerald-500'}`}>
                          {assessment.risk_level}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-xs text-slate-400 uppercase tracking-wider mb-1">SLA Status</div>
                        <div className="text-lg font-bold text-white">
                          {assessment.sla_status}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Grid for core metrics */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-4 border-t border-slate-700/50">
                    
                    {/* Historic Performance */}
                    <div className="bg-slate-800/80 p-4 rounded border border-slate-700/30">
                      <h4 className="text-sm font-medium text-slate-300 mb-3">Historical Performance</h4>
                      <div className="space-y-2 text-sm">
                        <div className="flex justify-between">
                          <span className="text-slate-400">Compliance Rate</span>
                          <span className="text-white">{assessment.historical_performance?.compliance_rate.toFixed(1)}%</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-400">Breaches</span>
                          <span className="text-white">{assessment.historical_performance?.breach_count} / {assessment.historical_performance?.total_commitments}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-400">Avg Delay</span>
                          <span className="text-white">{assessment.historical_performance?.average_delay_hours}h</span>
                        </div>
                      </div>
                    </div>

                    {/* Operational Exposures */}
                    <div className="bg-slate-800/80 p-4 rounded border border-slate-700/30">
                      <h4 className="text-sm font-medium text-slate-300 mb-3">Operational Exposure</h4>
                      <div className="space-y-2 text-sm">
                        <div className="flex justify-between">
                          <span className="text-slate-400">Demand Accel.</span>
                          <span className="text-white">{assessment.demand_exposure?.demand_acceleration}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-400">Capacity Utils</span>
                          <span className="text-white">{assessment.capacity_exposure?.utilization_percent}%</span>
                        </div>
                      </div>
                    </div>
                    
                    {/* Confidence & Provenance */}
                    <div className="bg-slate-800/80 p-4 rounded border border-slate-700/30">
                      <h4 className="text-sm font-medium text-slate-300 mb-3">Assessment Metadata</h4>
                      <div className="space-y-2 text-sm">
                        <div className="flex justify-between">
                          <span className="text-slate-400">Confidence</span>
                          <span className="text-white">{assessment.confidence}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-400">Provenance</span>
                          <span className="text-slate-300">{assessment.provenance}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-400">Model</span>
                          <span className="text-slate-300">{assessment.model_version}</span>
                        </div>
                      </div>
                    </div>

                  </div>

                  {/* Risk Factors */}
                  {assessment.factors && assessment.factors.length > 0 && (
                    <div className="pt-4 border-t border-slate-700/50">
                      <h4 className="text-sm font-medium text-slate-300 mb-3">Driving Risk Factors</h4>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {assessment.factors.map((factor: any, i: number) => (
                          <div key={i} className="flex flex-col bg-slate-900/50 p-3 rounded border border-slate-700/30 text-sm">
                            <div className="flex justify-between mb-1">
                              <span className="font-medium text-indigo-400">{factor.factor_name}</span>
                              <span className="text-slate-300">Score: {factor.score}</span>
                            </div>
                            <span className="text-slate-400 text-xs">{factor.explanation}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Evidence */}
                  {assessment.evidence && assessment.evidence.length > 0 && (
                    <div className="pt-4 border-t border-slate-700/50">
                      <h4 className="text-sm font-medium text-slate-300 mb-3">Operational Evidence</h4>
                      <div className="overflow-x-auto">
                        <table className="w-full text-left text-sm border-collapse">
                          <thead>
                            <tr className="border-b border-slate-700 text-slate-400">
                              <th className="pb-2 font-medium">Domain</th>
                              <th className="pb-2 font-medium">Type</th>
                              <th className="pb-2 font-medium">Timestamp</th>
                              <th className="pb-2 font-medium">Explanation</th>
                            </tr>
                          </thead>
                          <tbody>
                            {assessment.evidence.map((ev: any, i: number) => (
                              <tr key={i} className="border-b border-slate-800/50 last:border-0">
                                <td className="py-2 text-indigo-400 font-mono text-xs">{ev.source_domain}</td>
                                <td className="py-2 text-slate-300">{ev.evidence_type}</td>
                                <td className="py-2 text-slate-400 text-xs">{new Date(ev.observation_timestamp).toLocaleString()}</td>
                                <td className="py-2 text-slate-400">{ev.explanation}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {/* Data Quality Issues */}
                  {assessment.data_quality_issues && assessment.data_quality_issues.length > 0 && (
                    <div className="pt-4 border-t border-slate-700/50">
                      <div className="flex items-center space-x-2 text-amber-500 text-sm">
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                        </svg>
                        <span>Data Quality Exclusions: {assessment.data_quality_issues.join(", ")}</span>
                      </div>
                    </div>
                  )}

                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
