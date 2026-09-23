"use client";

import React, { useState } from 'react';

// Interfaces matching backend supplier_risk_contract.py
interface RiskFactor {
    factor_name: string;
    score: number;
    weight: number;
}

interface SupplierRiskEvidence {
    factor_type: string;
    observed_value: any;
    observation_count?: number;
    window_days?: number;
    metric?: string;
    source: string;
    timestamp: string;
}

interface SupplierExposure {
    affected_component_count: number;
    affected_sku_count: number;
    affected_order_count: number;
    forecast_exposure_units: number | null;
}

interface AnalyticalObservation {
    observation_type: string;
    description: string;
}

export interface SupplierRiskAssessment {
    tenant_id: string;
    supplier_id: string;
    assessment_id: string;
    assessment_timestamp: string;
    as_of_timestamp: string;
    risk_status: 'UNKNOWN' | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
    risk_score: number;
    confidence: 'LOW' | 'MEDIUM' | 'HIGH' | 'INSUFFICIENT_DATA';
    factors: RiskFactor[];
    evidence: SupplierRiskEvidence[];
    observations: AnalyticalObservation[];
    exposure_summary: SupplierExposure;
    data_quality_issues: string[];
    input_fingerprint: string;
}

interface SupplierRiskModalProps {
    isOpen: boolean;
    onClose: () => void;
    assessment: SupplierRiskAssessment | null;
}

export default function SupplierRiskModal({ isOpen, onClose, assessment }: SupplierRiskModalProps) {
    if (!isOpen) return null;

    const getStatusColor = (status: string) => {
        switch (status) {
            case 'LOW': return 'text-green-400 bg-green-400/10 border-green-400/20';
            case 'MEDIUM': return 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20';
            case 'HIGH': return 'text-orange-400 bg-orange-400/10 border-orange-400/20';
            case 'CRITICAL': return 'text-red-500 bg-red-500/10 border-red-500/20';
            default: return 'text-gray-400 bg-gray-400/10 border-gray-400/20';
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
            <div className="bg-slate-900 border border-slate-800 rounded-xl w-full max-w-4xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
                
                {/* Header */}
                <div className="px-6 py-4 border-b border-slate-800 flex justify-between items-center bg-slate-900/50">
                    <div>
                        <h2 className="text-xl font-bold text-white flex items-center gap-2">
                            <span className="text-blue-400">⚡</span> Supplier Risk Intelligence
                        </h2>
                        <p className="text-slate-400 text-sm mt-1">
                            Deterministic Read-Only Analytical Assessment
                        </p>
                    </div>
                    <button 
                        onClick={onClose}
                        className="text-slate-400 hover:text-white transition-colors p-2 rounded-lg hover:bg-slate-800"
                    >
                        ✕
                    </button>
                </div>

                {/* Content */}
                <div className="p-6 overflow-y-auto custom-scrollbar">
                    {!assessment ? (
                        <div className="text-center py-12 text-slate-400">
                            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto mb-4"></div>
                            Loading analytical assessment...
                        </div>
                    ) : (
                        <div className="space-y-6">
                            
                            {/* Overview Cards */}
                            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                                <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50">
                                    <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1">Supplier ID</div>
                                    <div className="text-xl text-white font-mono">{assessment.supplier_id}</div>
                                </div>
                                <div className={`rounded-lg p-4 border ${getStatusColor(assessment.risk_status)}`}>
                                    <div className="text-xs font-semibold uppercase tracking-wider mb-1 opacity-80">Risk Status</div>
                                    <div className="text-xl font-bold">{assessment.risk_status}</div>
                                </div>
                                <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50">
                                    <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1">Confidence</div>
                                    <div className="text-xl text-white">{assessment.confidence}</div>
                                </div>
                                <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50">
                                    <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1">Risk Score</div>
                                    <div className="text-xl text-white">{assessment.risk_score.toFixed(1)}</div>
                                </div>
                            </div>

                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                                {/* Risk Factors */}
                                <div className="space-y-4">
                                    <h3 className="text-lg font-semibold text-white flex items-center gap-2 border-b border-slate-800 pb-2">
                                        <span className="text-blue-400">📊</span> Risk Factors
                                    </h3>
                                    {assessment.factors.length > 0 ? (
                                        <div className="space-y-3">
                                            {assessment.factors.map((factor, idx) => (
                                                <div key={idx} className="bg-slate-800/30 rounded-lg p-3 border border-slate-700/30">
                                                    <div className="flex justify-between items-center mb-2">
                                                        <span className="text-slate-300 font-medium capitalize">{factor.factor_name.replace(/_/g, ' ')}</span>
                                                        <span className="text-slate-400 text-sm">Weight: {(factor.weight * 100).toFixed(0)}%</span>
                                                    </div>
                                                    <div className="w-full bg-slate-900 rounded-full h-2 overflow-hidden">
                                                        <div 
                                                            className={`h-full rounded-full ${factor.score > 70 ? 'bg-red-500' : factor.score > 30 ? 'bg-yellow-400' : 'bg-green-400'}`}
                                                            style={{ width: `${factor.score}%` }}
                                                        ></div>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    ) : (
                                        <div className="text-slate-500 italic p-4 bg-slate-800/20 rounded-lg border border-slate-800">
                                            No calculated risk factors available.
                                        </div>
                                    )}
                                </div>

                                {/* Exposure & Metadata */}
                                <div className="space-y-6">
                                    <div className="space-y-4">
                                        <h3 className="text-lg font-semibold text-white flex items-center gap-2 border-b border-slate-800 pb-2">
                                            <span className="text-purple-400">🔗</span> Operational Exposure
                                        </h3>
                                        <div className="grid grid-cols-2 gap-3">
                                            <div className="bg-slate-800/30 p-3 rounded-lg border border-slate-700/30">
                                                <div className="text-slate-400 text-xs mb-1">Components</div>
                                                <div className="text-lg text-white font-semibold">{assessment.exposure_summary?.affected_component_count || 0}</div>
                                            </div>
                                            <div className="bg-slate-800/30 p-3 rounded-lg border border-slate-700/30">
                                                <div className="text-slate-400 text-xs mb-1">Active Orders</div>
                                                <div className="text-lg text-white font-semibold">{assessment.exposure_summary?.affected_order_count || 0}</div>
                                            </div>
                                            <div className="bg-slate-800/30 p-3 rounded-lg border border-slate-700/30">
                                                <div className="text-slate-400 text-xs mb-1">SKUs</div>
                                                <div className="text-lg text-white font-semibold">{assessment.exposure_summary?.affected_sku_count || 0}</div>
                                            </div>
                                            <div className="bg-slate-800/30 p-3 rounded-lg border border-slate-700/30">
                                                <div className="text-slate-400 text-xs mb-1">Forecast Exposure</div>
                                                <div className="text-lg text-white font-semibold">
                                                    {assessment.exposure_summary?.forecast_exposure_units !== null ? assessment.exposure_summary?.forecast_exposure_units : 'UNKNOWN'}
                                                </div>
                                            </div>
                                        </div>
                                    </div>

                                    {/* Data Quality & Observations */}
                                    {assessment.observations?.length > 0 && (
                                        <div className="space-y-2">
                                            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                                                <span className="text-blue-400">💡</span> Analytical Observations
                                            </h3>
                                            <ul className="list-disc list-inside text-sm text-blue-200/70 bg-blue-400/5 p-3 rounded-lg border border-blue-400/10">
                                                {assessment.observations.map((obs, idx) => (
                                                    <li key={idx}><strong>{obs.observation_type}</strong>: {obs.description}</li>
                                                ))}
                                            </ul>
                                        </div>
                                    )}

                                    {assessment.data_quality_issues?.length > 0 && (
                                        <div className="space-y-2">
                                            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                                                <span className="text-yellow-400">⚠️</span> Data Quality Notices
                                            </h3>
                                            <ul className="list-disc list-inside text-sm text-yellow-200/70 bg-yellow-400/5 p-3 rounded-lg border border-yellow-400/10">
                                                {assessment.data_quality_issues.map((issue, idx) => (
                                                    <li key={idx}>{issue}</li>
                                                ))}
                                            </ul>
                                        </div>
                                    )}
                                </div>
                            </div>

                            {/* Evidence */}
                            <div className="space-y-4 pt-4 border-t border-slate-800">
                                <h3 className="text-lg font-semibold text-white flex items-center gap-2">
                                    <span className="text-emerald-400">📋</span> Structured Evidence
                                </h3>
                                <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
                                    <table className="w-full text-left text-sm">
                                        <thead className="bg-slate-800/50 text-slate-400">
                                            <tr>
                                                <th className="px-4 py-3 font-medium">Factor</th>
                                                <th className="px-4 py-3 font-medium">Source</th>
                                                <th className="px-4 py-3 font-medium">Observed Value</th>
                                                <th className="px-4 py-3 font-medium">Timestamp</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-slate-800/50">
                                            {assessment.evidence?.length > 0 ? assessment.evidence.map((ev, idx) => (
                                                <tr key={idx} className="hover:bg-slate-800/30 transition-colors text-slate-300">
                                                    <td className="px-4 py-3 capitalize">{ev.factor_type.replace(/_/g, ' ')}</td>
                                                    <td className="px-4 py-3 font-mono text-xs">{ev.source}</td>
                                                    <td className="px-4 py-3">
                                                        {typeof ev.observed_value === 'number' 
                                                            ? ev.observed_value.toFixed(3) 
                                                            : typeof ev.observed_value === 'object' 
                                                                ? JSON.stringify(ev.observed_value)
                                                                : String(ev.observed_value)}
                                                    </td>
                                                    <td className="px-4 py-3">{new Date(ev.timestamp).toLocaleString()}</td>
                                                </tr>
                                            )) : (
                                                <tr>
                                                    <td colSpan={4} className="px-4 py-8 text-center text-slate-500">
                                                        No structural evidence logged.
                                                    </td>
                                                </tr>
                                            )}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                            
                            {/* Deterministic Signature */}
                            <div className="pt-4 border-t border-slate-800 flex justify-between items-center text-xs text-slate-500">
                                <div>As of: {new Date(assessment.as_of_timestamp).toLocaleString()}</div>
                                <div className="font-mono" title="Deterministic Fingerprint">
                                    Signature: {assessment.input_fingerprint.substring(0, 16)}...
                                </div>
                            </div>
                            
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
