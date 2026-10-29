import React from "react";
import { redirect } from "next/navigation";
import { BackendAuthVerifier } from "@/components/BackendAuthVerifier";
import { AdminOperationsConsole } from "@/components/admin/AdminOperationsConsole";
import {
  calculateFallbackRatePct,
  computeLatencyPercentiles,
} from "@/lib/admin-utils";
import { auth, signOut } from "@/lib/auth";
import { fetchFastApiCurrentUser } from "@/lib/fastapi";
import { prisma } from "@/lib/prisma";

export default async function AdminIntegrationsAndDlqPage() {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }
  if (session.user.role === "AGENT") {
    redirect("/agent");
  }
  if (session.user.role === "MANAGER") {
    redirect("/manager");
  }

  const [integrations, allTickets, serverMeResponse] = await Promise.all([
    prisma.integration.findMany({
      orderBy: {
        createdAt: "desc",
      },
    }),
    prisma.ticket.findMany({
      include: {
        aiQaReport: true,
      },
      orderBy: {
        updatedAt: "desc",
      },
    }),
    fetchFastApiCurrentUser(session.accessToken),
  ]);

  const statusCounts: Record<string, number> = {
    QUEUED: 0,
    PROCESSING: 0,
    EVALUATED: 0,
    FAILED_RETRYABLE: 0,
    FAILED_PERMANENT: 0,
  };

  const latencies: number[] = [];
  let totalPromptTokens = 0;
  let totalCompletionTokens = 0;
  let totalReports = 0;
  let fallbackCount = 0;

  for (const tkt of allTickets) {
    const st = String(tkt.processingStatus);
    statusCounts[st] = (statusCounts[st] || 0) + 1;

    const meta =
      typeof tkt.ticketMetadata === "object" && tkt.ticketMetadata !== null
        ? (tkt.ticketMetadata as Record<string, unknown>)
        : {};

    if (tkt.aiQaReport) {
      totalReports += 1;
      latencies.push(tkt.aiQaReport.inferenceLatencyMs);
      totalPromptTokens += tkt.aiQaReport.promptTokens;
      totalCompletionTokens += tkt.aiQaReport.completionTokens;
      if (
        meta.fallback_model_used === true ||
        tkt.aiQaReport.modelUsed.toLowerCase().includes("fallback")
      ) {
        fallbackCount += 1;
      }
    }
  }

  const latency = computeLatencyPercentiles(latencies);
  const fallbackRatePct = calculateFallbackRatePct(fallbackCount, totalReports);

  const dlqTickets = allTickets
    .filter(
      (t) =>
        String(t.processingStatus) === "FAILED_RETRYABLE" ||
        String(t.processingStatus) === "FAILED_PERMANENT"
    )
    .map((t) => {
      const meta =
        typeof t.ticketMetadata === "object" && t.ticketMetadata !== null
          ? (t.ticketMetadata as Record<string, unknown>)
          : {};
      return {
        ticket_id: t.id,
        external_ticket_id: t.externalTicketId,
        subject: t.subject,
        processing_status: String(t.processingStatus),
        last_error: String(
          meta.last_dlq_error ||
            meta.last_error ||
            "AI evaluation failed after maximum retries."
        ),
        updated_at: t.updatedAt.toISOString(),
      };
    });

  const serializedIntegrations = integrations.map((item) => ({
    id: item.id,
    name: item.name,
    crmType: String(item.crmType),
    subdomainOrBaseUrl: item.subdomainOrBaseUrl,
    encryptedApiKey: item.encryptedApiKey,
    isActive: item.isActive,
    lastSuccessfulSyncAt: item.lastSuccessfulSyncAt
      ? item.lastSuccessfulSyncAt.toISOString()
      : null,
  }));

  async function handleSignOut() {
    "use server";
    await signOut({ redirectTo: "/login" });
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold bg-purple-500/10 text-purple-300 border border-purple-500/30">
            RBAC Guard: ADMIN ONLY • Observability &amp; DLQ Replay Console
          </span>
          <h1 className="mt-2 text-2xl font-bold text-white">
            Admin CRM Integrations, AI Telemetry &amp; Dead-Letter Queue Replay
          </h1>
          <p className="text-sm text-slate-400">
            Authenticated as{" "}
            <span className="text-slate-200 font-medium">
              {session.user.fullName}
            </span>{" "}
            ({session.user.email}) • Role:{" "}
            <code className="text-purple-300 font-mono">
              {session.user.role}
            </code>
          </p>
        </div>

        <form action={handleSignOut}>
          <button
            type="submit"
            className="rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 px-4 py-2 text-xs font-semibold text-white transition"
          >
            Sign Out
          </button>
        </form>
      </div>

      <AdminOperationsConsole
        integrations={serializedIntegrations}
        telemetry={{
          latency,
          totalPromptTokens,
          totalCompletionTokens,
          totalReports,
          fallbackCount,
          fallbackRatePct,
          statusCounts,
        }}
        dlqTickets={dlqTickets}
      />

      {/* Cross-Service FastAPI Token Verifier */}
      <BackendAuthVerifier
        accessToken={session.accessToken}
        initialServerMeResponse={serverMeResponse}
      />
    </div>
  );
}
