"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import {
  type DlqTicketSummary,
  type LatencyPercentilesResult,
  buildWebhookEndpointUrl,
  filterDlqTickets,
  formatTokenCount,
  maskEncryptedSecret,
} from "@/lib/admin-utils";

export interface AdminIntegrationRow {
  id: string;
  name: string;
  crmType: string;
  subdomainOrBaseUrl: string;
  encryptedApiKey: string;
  isActive: boolean;
  lastSuccessfulSyncAt: string | null;
}

export interface AdminTelemetryProps {
  latency: LatencyPercentilesResult;
  totalPromptTokens: number;
  totalCompletionTokens: number;
  totalReports: number;
  fallbackCount: number;
  fallbackRatePct: number;
  statusCounts: Record<string, number>;
}

export function AdminOperationsConsole({
  integrations,
  telemetry,
  dlqTickets,
}: {
  integrations: AdminIntegrationRow[];
  telemetry: AdminTelemetryProps;
  dlqTickets: DlqTicketSummary[];
}) {
  const router = useRouter();

  // New Integration Form State
  const [name, setName] = useState("");
  const [crmType, setCrmType] = useState("ZENDESK");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  // Sync & Replay Action State
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [replayingId, setReplayingId] = useState<string | null>(null);
  const [isReplayingAll, setIsReplayingAll] = useState(false);
  const [dlqFilter, setDlqFilter] = useState<
    "ALL" | "FAILED_RETRYABLE" | "FAILED_PERMANENT"
  >("ALL");
  const [notice, setNotice] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  const filteredDlq = filterDlqTickets(dlqTickets, dlqFilter);

  async function handleCreateIntegration(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !baseUrl.trim() || !apiKey.trim() || !webhookSecret.trim()) {
      setNotice({
        type: "error",
        text: "All CRM integration fields (Name, Subdomain/URL, API Key, Webhook Secret) are required.",
      });
      return;
    }

    setIsCreating(true);
    setNotice(null);
    try {
      const res = await fetch("/api/v1/integrations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          crm_type: crmType,
          subdomain_or_base_url: baseUrl.trim(),
          api_key: apiKey.trim(),
          webhook_secret: webhookSecret.trim(),
          is_active: true,
        }),
      });
      if (!res.ok) {
        setNotice({
          type: "error",
          text: `Failed to register CRM connector (HTTP ${res.status}).`,
        });
      } else {
        setNotice({
          type: "success",
          text: `Registered ${crmType} integration "${name.trim()}" with AES-256-GCM encrypted credentials.`,
        });
        setName("");
        setBaseUrl("");
        setApiKey("");
        setWebhookSecret("");
        router.refresh();
      }
    } catch {
      setNotice({
        type: "error",
        text: "Network error registering CRM integration.",
      });
    } finally {
      setIsCreating(false);
    }
  }

  async function handleTriggerSync(integrationId: string) {
    setSyncingId(integrationId);
    setNotice(null);
    try {
      const res = await fetch(`/api/v1/integrations/${integrationId}/sync`, {
        method: "POST",
      });
      if (res.ok) {
        const data = (await res.json()) as { newly_ingested_count?: number };
        setNotice({
          type: "success",
          text: `Delta-sync completed! Ingested ${data.newly_ingested_count ?? 0} missed closed tickets.`,
        });
        router.refresh();
      } else {
        setNotice({
          type: "error",
          text: `Delta-sync failed (HTTP ${res.status}).`,
        });
      }
    } finally {
      setSyncingId(null);
    }
  }

  async function handleReplayTicket(ticketId: string) {
    setReplayingId(ticketId);
    setNotice(null);
    try {
      const res = await fetch(`/api/v1/admin/dlq/${ticketId}/replay`, {
        method: "POST",
      });
      if (res.ok) {
        setNotice({
          type: "success",
          text: `Ticket ${ticketId.slice(0, 8)} replayed and evaluated!`,
        });
        router.refresh();
      } else {
        setNotice({
          type: "error",
          text: `DLQ replay failed (HTTP ${res.status}).`,
        });
      }
    } finally {
      setReplayingId(null);
    }
  }

  async function handleReplayAll() {
    setIsReplayingAll(true);
    setNotice(null);
    try {
      const res = await fetch("/api/v1/admin/dlq/replay-all", {
        method: "POST",
      });
      if (res.ok) {
        const data = (await res.json()) as { succeeded_count?: number };
        setNotice({
          type: "success",
          text: `Batch DLQ replay complete (${data.succeeded_count ?? 0} tickets evaluated).`,
        });
        router.refresh();
      }
    } finally {
      setIsReplayingAll(false);
    }
  }

  const totalTokens =
    telemetry.totalPromptTokens + telemetry.totalCompletionTokens;

  return (
    <div className="space-y-8">
      {notice && (
        <div
          className={`rounded-xl px-4 py-3 text-xs font-medium border ${
            notice.type === "success"
              ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-200"
              : "bg-rose-500/15 border-rose-500/30 text-rose-200"
          }`}
        >
          {notice.text}
        </div>
      )}

      {/* 1. AI Observability & Latency Telemetry Ribbon */}
      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Inference Latency (p50 / p95 / p99)
          </div>
          <div className="mt-3 text-lg font-mono font-bold text-white">
            {telemetry.latency.p50_latency_ms}ms{" "}
            <span className="text-slate-500">/</span>{" "}
            <span className="text-indigo-300">
              {telemetry.latency.p95_latency_ms}ms
            </span>{" "}
            <span className="text-slate-500">/</span>{" "}
            <span className="text-amber-300">
              {telemetry.latency.p99_latency_ms}ms
            </span>
          </div>
          <div className="mt-1 text-xs text-slate-400">
            Avg: {telemetry.latency.avg_latency_ms}ms across{" "}
            {telemetry.latency.sample_size} reports
          </div>
        </div>

        <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Groq Token Consumption
          </div>
          <div className="mt-3 text-2xl font-mono font-bold text-emerald-300">
            {formatTokenCount(totalTokens)}
          </div>
          <div className="mt-1 text-xs text-slate-400 font-mono">
            Prompt: {formatTokenCount(telemetry.totalPromptTokens)} •
            Completion: {formatTokenCount(telemetry.totalCompletionTokens)}
          </div>
        </div>

        <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Model Fallback Rate (8B Instant)
          </div>
          <div className="mt-3 text-2xl font-mono font-bold text-indigo-300">
            {telemetry.fallbackRatePct}%
          </div>
          <div className="mt-1 text-xs text-slate-400">
            {telemetry.fallbackCount} of {telemetry.totalReports} evaluations
            used fallback
          </div>
        </div>

        <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Pipeline &amp; DLQ Queue Health
          </div>
          <div className="mt-3 flex items-center gap-3 font-mono text-xs">
            <span className="px-2 py-1 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
              EVAL: {telemetry.statusCounts.EVALUATED ?? 0}
            </span>
            <span className="px-2 py-1 rounded bg-indigo-500/15 text-indigo-300 border border-indigo-500/30">
              QUEUED: {telemetry.statusCounts.QUEUED ?? 0}
            </span>
            <span className="px-2 py-1 rounded bg-rose-500/15 text-rose-300 border border-rose-500/30">
              DLQ: {dlqTickets.length}
            </span>
          </div>
          <div className="mt-1.5 text-xs text-slate-400">
            Rate-limited Redis Lua RPM/TPM guard active
          </div>
        </div>
      </section>

      {/* 2. CRM Connectors & Register New Connector Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Configured CRM Connectors List */}
        <section className="lg:col-span-2 rounded-xl bg-slate-900 border border-slate-800 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-bold text-white">
                Provisioned External Support CRM Connectors ({integrations.length})
              </h2>
              <p className="text-xs text-slate-400">
                HMAC-SHA256 verified webhooks + 15-minute scheduled delta-sync
                reconciler
              </p>
            </div>
          </div>

          <div className="space-y-3">
            {integrations.map((item) => {
              const webhookPath = buildWebhookEndpointUrl(
                item.crmType,
                item.id
              );
              return (
                <div
                  key={item.id}
                  className="rounded-xl bg-slate-950 border border-slate-800 p-4 space-y-3"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2.5">
                      <span className="text-sm font-bold text-white">
                        {item.name}
                      </span>
                      <span className="px-2 py-0.5 rounded text-xs font-mono bg-indigo-500/15 text-indigo-300 border border-indigo-500/30">
                        {item.crmType}
                      </span>
                      <span
                        className={`px-2 py-0.5 rounded text-xs font-mono ${
                          item.isActive
                            ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                            : "bg-slate-800 text-slate-400"
                        }`}
                      >
                        {item.isActive ? "ACTIVE" : "DISABLED"}
                      </span>
                    </div>

                    <button
                      type="button"
                      disabled={syncingId === item.id}
                      onClick={() => handleTriggerSync(item.id)}
                      className="rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/30 disabled:opacity-50 px-3 py-1.5 text-xs font-semibold text-indigo-200 transition"
                    >
                      {syncingId === item.id
                        ? "Syncing..."
                        : "↻ Trigger Delta-Sync"}
                    </button>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs font-mono text-slate-400">
                    <div>
                      <span className="text-slate-500">Base URL: </span>
                      <span className="text-slate-200">
                        {item.subdomainOrBaseUrl}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-500">At-Rest Crypto: </span>
                      <span className="text-emerald-300">
                        {maskEncryptedSecret(item.encryptedApiKey)}
                      </span>
                    </div>
                    <div className="md:col-span-2">
                      <span className="text-slate-500">Webhook Endpoint: </span>
                      <code className="text-indigo-300">{webhookPath}</code>
                    </div>
                  </div>

                  <div className="text-[11px] font-mono text-slate-500 flex justify-between border-t border-slate-900 pt-2">
                    <span>Integration ID: {item.id}</span>
                    <span>
                      Last Sync:{" "}
                      {item.lastSuccessfulSyncAt
                        ? new Date(item.lastSuccessfulSyncAt).toLocaleString()
                        : "Never"}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* Register New CRM Integration Form */}
        <section className="rounded-xl bg-slate-900 border border-slate-800 p-6 space-y-4">
          <div>
            <h2 className="text-base font-bold text-white">
              Register New CRM Connector
            </h2>
            <p className="text-xs text-slate-400">
              Credentials are encrypted at rest via AES-256-GCM
            </p>
          </div>

          <form onSubmit={handleCreateIntegration} className="space-y-3.5">
            <div>
              <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">
                Connector Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Intercom EU Production"
                className="w-full rounded-lg bg-slate-950 border border-slate-800 px-3 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div>
              <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">
                CRM Provider
              </label>
              <select
                value={crmType}
                onChange={(e) => setCrmType(e.target.value)}
                className="w-full rounded-lg bg-slate-950 border border-slate-800 px-3 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
              >
                <option value="ZENDESK">ZENDESK</option>
                <option value="INTERCOM">INTERCOM</option>
                <option value="FRESHDESK">FRESHDESK</option>
                <option value="CUSTOM">CUSTOM</option>
              </select>
            </div>

            <div>
              <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">
                Subdomain or API Base URL
              </label>
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://acme-support.zendesk.com"
                className="w-full rounded-lg bg-slate-950 border border-slate-800 px-3 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div>
              <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">
                CRM API Key (AES-256-GCM Encrypted)
              </label>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="Enter CRM REST API Token"
                className="w-full rounded-lg bg-slate-950 border border-slate-800 px-3 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div>
              <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">
                Webhook Signing Secret (HMAC-SHA256)
              </label>
              <input
                type="password"
                value={webhookSecret}
                onChange={(e) => setWebhookSecret(e.target.value)}
                placeholder="Enter Webhook Shared Secret"
                className="w-full rounded-lg bg-slate-950 border border-slate-800 px-3 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
              />
            </div>

            <button
              type="submit"
              disabled={isCreating}
              className="w-full rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 py-2 text-xs font-bold text-white transition"
            >
              {isCreating
                ? "Encrypting & Provisioning..."
                : "+ Provision CRM Connector"}
            </button>
          </form>
        </section>
      </div>

      {/* 3. Dead-Letter Queue (DLQ) & Failed Evaluations Replay Table */}
      <section className="rounded-xl bg-slate-900 border border-slate-800 p-6 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-bold text-white">
              Dead-Letter Queue (`ai_evaluation_dlq`) &amp; One-Click Replay
            </h2>
            <p className="text-xs text-slate-400">
              Tickets that exhausted primary and fallback model retries are
              parked here as <code className="font-mono">FAILED_RETRYABLE</code>{" "}
              for zero-data-loss replay.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <select
              value={dlqFilter}
              onChange={(e) =>
                setDlqFilter(
                  e.target.value as
                    | "ALL"
                    | "FAILED_RETRYABLE"
                    | "FAILED_PERMANENT"
                )
              }
              className="rounded-lg bg-slate-950 border border-slate-800 px-3 py-1.5 text-xs text-slate-200"
            >
              <option value="ALL">All Failed Statuses</option>
              <option value="FAILED_RETRYABLE">FAILED_RETRYABLE</option>
              <option value="FAILED_PERMANENT">FAILED_PERMANENT</option>
            </select>

            {dlqTickets.length > 0 && (
              <button
                type="button"
                disabled={isReplayingAll}
                onClick={handleReplayAll}
                className="rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 px-3.5 py-1.5 text-xs font-bold text-white transition"
              >
                {isReplayingAll
                  ? "Replaying All..."
                  : `↻ Replay All Failed Tickets (${dlqTickets.length})`}
              </button>
            )}
          </div>
        </div>

        {filteredDlq.length === 0 ? (
          <div className="rounded-xl bg-slate-950 border border-slate-800 p-8 text-center text-xs text-emerald-300 font-mono">
            ✓ Dead-Letter Queue is empty — 0 failed ticket evaluations pending
            replay.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-[11px] uppercase text-slate-400">
                  <th className="py-3 pr-4">External ID</th>
                  <th className="py-3 pr-4">Subject</th>
                  <th className="py-3 pr-4">Status</th>
                  <th className="py-3 pr-4">Failure Reason</th>
                  <th className="py-3 text-right">Replay Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/70">
                {filteredDlq.map((item) => (
                  <tr key={item.ticket_id}>
                    <td className="py-3 pr-4 font-mono text-xs text-indigo-300">
                      {item.external_ticket_id}
                    </td>
                    <td className="py-3 pr-4 text-xs text-slate-200">
                      {item.subject}
                    </td>
                    <td className="py-3 pr-4">
                      <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-rose-500/15 text-rose-300 border border-rose-500/30">
                        {item.processing_status}
                      </span>
                    </td>
                    <td className="py-3 pr-4 text-xs font-mono text-rose-200 max-w-md truncate">
                      {item.last_error}
                    </td>
                    <td className="py-3 text-right">
                      <button
                        type="button"
                        disabled={replayingId === item.ticket_id}
                        onClick={() => handleReplayTicket(item.ticket_id)}
                        className="rounded-lg bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-500/30 px-3 py-1 text-xs font-semibold text-emerald-200 transition"
                      >
                        {replayingId === item.ticket_id
                          ? "Replaying..."
                          : "↻ Replay AI Evaluation"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

