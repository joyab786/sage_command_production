"use client";

import React from "react";

interface ForecastPoint {
    timestamp: string;
    value: number;
    lower_bound?: number;
    upper_bound?: number;
}

interface ForecastEvidence {
    evidence_id: string;
    factor_type: string;
    source: string;
    explanation: string;
    contribution: number;
    confidence: number;
}

interface ForecastRecommendation {
    recommendation_id: string;
    observation_type: string;
    description: string;
}

interface ForecastContext {
    anomalies_considered: number;
    data_quality_score: number;
    related_events: number;
    digital_twin_state_available: boolean;
    knowledge_graph_relationships: number;
}

interface DemandForecast {
    forecast_id: string;
    demand_entity_id: string;
    demand_entity_name: string;
    forecast_horizon: string;
    forecast_granularity: string;
    forecast_values: ForecastPoint[];
    confidence: string;
    uncertainty: string;
    trend_context: string;
    seasonality_context: string;
    method_selected: string;
    evidence: ForecastEvidence[];
    recommendations: ForecastRecommendation[];
    context: ForecastContext;
    provenance: string;
    model_version: string;
}

export function DemandForecastingModal({ 
    forecast, 
    onClose 
}: { 
    forecast: DemandForecast | null, 
    onClose: () => void 
}) {
    if (!forecast) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
            <div className="bg-slate-900 border border-slate-700 shadow-2xl rounded-xl w-full max-w-4xl max-h-[90vh] overflow-y-auto flex flex-col">
                {/* Header */}
                <div className="sticky top-0 bg-slate-900 border-b border-slate-800 px-6 py-4 flex items-center justify-between z-10">
                    <div>
                        <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
                            <span>Demand Forecasting Intelligence</span>
                            <span className="text-xs px-2 py-1 bg-blue-500/20 text-blue-300 rounded border border-blue-500/30 uppercase tracking-wider">Analytical Only</span>
                        </h2>
                        <p className="text-slate-400 text-sm mt-1">Entity: {forecast.demand_entity_name} ({forecast.demand_entity_id})</p>
                    </div>
                    <button onClick={onClose} className="text-slate-400 hover:text-white p-2">
                        ✕
                    </button>
                </div>

                {/* Content */}
                <div className="p-6 space-y-8 flex-1">
                    
                    {/* Top Stats */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <div className="bg-slate-800 p-4 rounded-lg border border-slate-700">
                            <p className="text-slate-400 text-xs uppercase mb-1">Methodology</p>
                            <p className="text-slate-200 font-mono text-sm">{forecast.method_selected}</p>
                        </div>
                        <div className="bg-slate-800 p-4 rounded-lg border border-slate-700">
                            <p className="text-slate-400 text-xs uppercase mb-1">Horizon / Granularity</p>
                            <p className="text-slate-200 font-mono text-sm">{forecast.forecast_horizon} / {forecast.forecast_granularity}</p>
                        </div>
                        <div className="bg-slate-800 p-4 rounded-lg border border-slate-700">
                            <p className="text-slate-400 text-xs uppercase mb-1">Trend</p>
                            <p className="text-slate-200 font-mono text-sm">{forecast.trend_context}</p>
                        </div>
                        <div className="bg-slate-800 p-4 rounded-lg border border-slate-700">
                            <p className="text-slate-400 text-xs uppercase mb-1">Confidence</p>
                            <p className={`font-mono text-sm ${forecast.confidence === 'HIGH' ? 'text-green-400' : forecast.confidence === 'MEDIUM' ? 'text-yellow-400' : 'text-red-400'}`}>
                                {forecast.confidence}
                            </p>
                        </div>
                    </div>

                    <div className="bg-blue-900/20 border border-blue-800/50 p-4 rounded-lg flex flex-col gap-1">
                        <p className="text-blue-300 text-sm font-semibold">Uncertainty Context</p>
                        <p className="text-slate-300 text-sm">{forecast.uncertainty}</p>
                    </div>

                    {/* Forecast Table */}
                    <div>
                        <h3 className="text-lg font-semibold text-slate-200 mb-4 border-b border-slate-700 pb-2">Forecast Trajectory</h3>
                        {forecast.forecast_values.length > 0 ? (
                            <div className="overflow-x-auto border border-slate-700 rounded-lg">
                                <table className="w-full text-left text-sm text-slate-300">
                                    <thead className="bg-slate-800 text-slate-400 uppercase text-xs">
                                        <tr>
                                            <th className="px-4 py-3 border-b border-slate-700">Timestamp</th>
                                            <th className="px-4 py-3 border-b border-slate-700">Point Forecast</th>
                                            <th className="px-4 py-3 border-b border-slate-700">Lower Bound</th>
                                            <th className="px-4 py-3 border-b border-slate-700">Upper Bound</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-700/50 bg-slate-900/50">
                                        {forecast.forecast_values.map((pt, idx) => (
                                            <tr key={idx} className="hover:bg-slate-800/50">
                                                <td className="px-4 py-2 font-mono text-xs">{pt.timestamp}</td>
                                                <td className="px-4 py-2 font-mono text-blue-300">{pt.value.toFixed(2)}</td>
                                                <td className="px-4 py-2 font-mono text-slate-400">{pt.lower_bound?.toFixed(2) || 'N/A'}</td>
                                                <td className="px-4 py-2 font-mono text-slate-400">{pt.upper_bound?.toFixed(2) || 'N/A'}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        ) : (
                            <p className="text-slate-500 italic text-sm">No forecast points generated. Insufficient data.</p>
                        )}
                    </div>

                    {/* Insights & Recommendations */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <h3 className="text-lg font-semibold text-slate-200 mb-4 border-b border-slate-700 pb-2">Analytical Insights</h3>
                            {forecast.recommendations.length > 0 ? (
                                <ul className="space-y-3">
                                    {forecast.recommendations.map(rec => (
                                        <li key={rec.recommendation_id} className="bg-slate-800/50 p-3 rounded border border-slate-700">
                                            <span className="inline-block bg-slate-700 text-slate-300 text-xs px-2 py-0.5 rounded mb-2">{rec.observation_type}</span>
                                            <p className="text-sm text-slate-300">{rec.description}</p>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <p className="text-slate-500 italic text-sm">No specific insights derived.</p>
                            )}
                        </div>

                        <div>
                            <h3 className="text-lg font-semibold text-slate-200 mb-4 border-b border-slate-700 pb-2">Context & Integration</h3>
                            <div className="bg-slate-800/50 p-4 rounded-lg border border-slate-700 space-y-2 text-sm">
                                <div className="flex justify-between">
                                    <span className="text-slate-400">Data Quality Score:</span>
                                    <span className={forecast.context.data_quality_score > 80 ? "text-green-400" : "text-yellow-400"}>{forecast.context.data_quality_score}%</span>
                                </div>
                                <div className="flex justify-between">
                                    <span className="text-slate-400">Anomalies Considered:</span>
                                    <span className="text-slate-200">{forecast.context.anomalies_considered}</span>
                                </div>
                                <div className="flex justify-between">
                                    <span className="text-slate-400">Related Events:</span>
                                    <span className="text-slate-200">{forecast.context.related_events}</span>
                                </div>
                                <div className="flex justify-between">
                                    <span className="text-slate-400">Digital Twin State:</span>
                                    <span className="text-slate-200">{forecast.context.digital_twin_state_available ? "Available" : "Not Linked"}</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Evidence */}
                    <div>
                        <h3 className="text-lg font-semibold text-slate-200 mb-4 border-b border-slate-700 pb-2">Evidence & Provenance</h3>
                        {forecast.evidence.length > 0 ? (
                            <div className="space-y-3">
                                {forecast.evidence.map(ev => (
                                    <div key={ev.evidence_id} className="bg-slate-800 p-3 rounded-lg border border-slate-700 flex gap-4 text-sm">
                                        <div className="flex-none">
                                            <span className="text-xs bg-slate-700 text-slate-300 px-2 py-1 rounded">{ev.factor_type}</span>
                                        </div>
                                        <div className="flex-1">
                                            <p className="text-slate-200">{ev.explanation}</p>
                                            <p className="text-slate-500 text-xs mt-1">Source: {ev.source} | Confidence: {(ev.confidence * 100).toFixed(0)}%</p>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <p className="text-slate-500 italic text-sm">No explicit evidence recorded.</p>
                        )}
                    </div>

                    {/* Metadata Footer */}
                    <div className="text-xs text-slate-500 border-t border-slate-800 pt-4 flex flex-wrap gap-4 mt-8">
                        <p>ID: <span className="font-mono text-slate-400">{forecast.forecast_id}</span></p>
                        <p>Model: <span className="font-mono text-slate-400">{forecast.model_version}</span></p>
                        <p>Provenance: <span className="font-mono text-slate-400">{forecast.provenance}</span></p>
                    </div>

                </div>
            </div>
        </div>
    );
}
