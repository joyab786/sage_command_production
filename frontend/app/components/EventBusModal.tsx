"use client";

import React, { useState, useEffect } from "react";
import { format } from "date-fns";
import { fetchSage } from "../../lib/api";
import { ScrollArea } from "../ui/scroll-area";
import { Badge } from "../ui/badge";

export function EventBusModal({ onClose }: { onClose: () => void }) {
  const [status, setStatus] = useState<any>(null);
  const [subscriptions, setSubscriptions] = useState<any[]>([]);
  const [deliveries, setDeliveries] = useState<any[]>([]);
  const [deadLetters, setDeadLetters] = useState<any[]>([]);

  useEffect(() => {
    async function loadData() {
      try {
        const [stRes, subRes, delRes, dlRes] = await Promise.all([
          fetchSage("/api/v3/event-bus/status"),
          fetchSage("/api/v3/event-bus/subscriptions"),
          fetchSage("/api/v3/event-bus/deliveries?limit=50"),
          fetchSage("/api/v3/event-bus/dead-letters?limit=50"),
        ]);
        setStatus(stRes);
        setSubscriptions(subRes);
        setDeliveries(delRes);
        setDeadLetters(dlRes);
      } catch (err) {
        console.error("Failed to load Event Bus data", err);
      }
    }
    loadData();
    const interval = setInterval(loadData, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-sage-900 border border-sage-700 rounded-xl shadow-2xl w-full max-w-6xl max-h-[90vh] overflow-hidden flex flex-col text-sage-100">
        
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-sage-800 bg-sage-900/50">
          <div>
            <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-cyan-300">
              Event Bus Dispatcher
            </h2>
            <p className="text-sm text-sage-400 mt-1">
              Read-only inspection of internal subscriptions, queue bounds, and delivery states.
            </p>
          </div>
          <button onClick={onClose} className="text-sage-400 hover:text-white transition-colors">
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-8">
          {/* Status Indicators */}
          <div className="grid grid-cols-4 gap-4">
            <div className="bg-sage-800 p-4 rounded-lg border border-sage-700 flex flex-col items-center justify-center">
              <span className="text-sage-400 text-xs uppercase tracking-wider mb-1">Bus Status</span>
              <Badge variant={status?.running ? "success" : "destructive"}>
                {status?.running ? "ACTIVE" : "OFFLINE"}
              </Badge>
            </div>
            <div className="bg-sage-800 p-4 rounded-lg border border-sage-700 flex flex-col items-center justify-center">
              <span className="text-sage-400 text-xs uppercase tracking-wider mb-1">Queue Size</span>
              <span className="text-xl font-mono text-cyan-300">{status?.queue_size ?? 0}</span>
            </div>
            <div className="bg-sage-800 p-4 rounded-lg border border-sage-700 flex flex-col items-center justify-center">
              <span className="text-sage-400 text-xs uppercase tracking-wider mb-1">Active Workers</span>
              <span className="text-xl font-mono text-blue-300">{status?.active_workers ?? 0}</span>
            </div>
            <div className="bg-sage-800 p-4 rounded-lg border border-sage-700 flex flex-col items-center justify-center">
              <span className="text-sage-400 text-xs uppercase tracking-wider mb-1">Dead Letters</span>
              <span className="text-xl font-mono text-red-400">{deadLetters.length}</span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-6">
            {/* Subscriptions */}
            <div className="bg-sage-800/50 rounded-lg border border-sage-700 p-4">
              <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                Active Subscriptions <Badge variant="secondary">{subscriptions.length}</Badge>
              </h3>
              <ScrollArea className="h-64 rounded-md border border-sage-700 bg-sage-900/50 p-2">
                {subscriptions.map(sub => (
                  <div key={sub.subscription_id} className="p-3 mb-2 rounded border border-sage-700 bg-sage-800 text-sm font-mono">
                    <div className="flex justify-between text-xs text-sage-400 mb-2">
                      <span>{sub.subscriber_id}</span>
                      <span>{sub.category || "ALL"}</span>
                    </div>
                    <div className="truncate text-sage-300">{sub.subscription_id}</div>
                  </div>
                ))}
              </ScrollArea>
            </div>

            {/* Recent Deliveries */}
            <div className="bg-sage-800/50 rounded-lg border border-sage-700 p-4">
              <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                Recent Deliveries
              </h3>
              <ScrollArea className="h-64 rounded-md border border-sage-700 bg-sage-900/50 p-2">
                {deliveries.map(del => (
                  <div key={del.delivery_id} className="p-3 mb-2 rounded border border-sage-700 bg-sage-800 text-sm font-mono">
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-sage-400 truncate w-32">{del.event_id}</span>
                      <Badge variant={del.status === 'SUCCESS' ? 'success' : del.status === 'FAILED' ? 'destructive' : 'warning'}>
                        {del.status}
                      </Badge>
                    </div>
                    <div className="text-xs text-sage-500 flex justify-between">
                      <span>Att: {del.attempts}/{del.max_attempts}</span>
                      <span>{format(new Date(del.updated_at), "HH:mm:ss.SSS")}</span>
                    </div>
                  </div>
                ))}
              </ScrollArea>
            </div>
          </div>
        </div>
        
      </div>
    </div>
  );
}
