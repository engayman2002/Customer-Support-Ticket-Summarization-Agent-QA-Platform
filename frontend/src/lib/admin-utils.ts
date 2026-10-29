export interface LatencyPercentilesResult {
  p50_latency_ms: number;
  p95_latency_ms: number;
  p99_latency_ms: number;
  avg_latency_ms: number;
  sample_size: number;
}

export interface DlqTicketSummary {
  ticket_id: string;
  external_ticket_id: string;
  subject: string;
  processing_status: string;
  last_error: string;
  updated_at: string | null;
}

/**
 * Compute p50, p95, p99, and average inference latency from an array of millisecond timings.
 */
export function computeLatencyPercentiles(
  latenciesMs: number[] | null | undefined
): LatencyPercentilesResult {
  const valid = (latenciesMs || []).filter(
    (v) => typeof v === "number" && !Number.isNaN(v) && v >= 0
  );
  if (valid.length === 0) {
    return {
      p50_latency_ms: 0,
      p95_latency_ms: 0,
      p99_latency_ms: 0,
      avg_latency_ms: 0,
      sample_size: 0,
    };
  }

  const sorted = [...valid].sort((a, b) => a - b);
  const interpolate = (pct: number): number => {
    if (sorted.length === 1) return sorted[0];
    const pos = (pct / 100) * (sorted.length - 1);
    const lower = Math.floor(pos);
    const upper = Math.ceil(pos);
    if (lower === upper) return Number(sorted[lower].toFixed(1));
    const weight = pos - lower;
    return Number(
      (sorted[lower] * (1 - weight) + sorted[upper] * weight).toFixed(1)
    );
  };

  const sum = sorted.reduce((acc, v) => acc + v, 0);
  return {
    p50_latency_ms: interpolate(50),
    p95_latency_ms: interpolate(95),
    p99_latency_ms: interpolate(99),
    avg_latency_ms: Number((sum / sorted.length).toFixed(1)),
    sample_size: sorted.length,
  };
}

/**
 * Calculate the fallback model invocation percentage (`0..100` rounded to 1 decimal place).
 */
export function calculateFallbackRatePct(
  fallbackCount: number,
  totalReports: number
): number {
  if (!totalReports || totalReports <= 0 || fallbackCount <= 0) {
    return 0;
  }
  return Number(((fallbackCount / totalReports) * 100).toFixed(1));
}

/**
 * Format large token numbers into human-readable strings (e.g., `15,420` or `1.2M`).
 */
export function formatTokenCount(tokens: number | null | undefined): string {
  const n = typeof tokens === "number" && !Number.isNaN(tokens) ? tokens : 0;
  if (n >= 1_000_000) {
    return `${(n / 1_000_000).toFixed(2)}M`;
  }
  return n.toLocaleString("en-US");
}

/**
 * Mask an AES-256-GCM ciphertext (`enc_aes256gcm_v1:...`) for safe display in the Admin UI.
 */
export function maskEncryptedSecret(ciphertext: string | null | undefined): string {
  if (!ciphertext || ciphertext.trim() === "") {
    return "Not Configured";
  }
  if (ciphertext.startsWith("enc_aes256gcm_v1:")) {
    return "enc_aes256gcm_v1:•••••••••••••••• (AES-256-GCM)";
  }
  return "•••••••••••••••• (Encrypted)";
}

/**
 * Build the canonical Webhook Ingestion endpoint path for a CRM integration.
 */
export function buildWebhookEndpointUrl(
  crmType: string,
  integrationId: string
): string {
  return `/api/v1/webhooks/${(crmType || "custom").toLowerCase()}/${integrationId}`;
}

/**
 * Filter DLQ ticket items by status (`ALL`, `FAILED_RETRYABLE`, `FAILED_PERMANENT`) and search query.
 */
export function filterDlqTickets(
  tickets: DlqTicketSummary[],
  statusFilter: "ALL" | "FAILED_RETRYABLE" | "FAILED_PERMANENT" = "ALL",
  searchQuery = ""
): DlqTicketSummary[] {
  return (tickets || []).filter((t) => {
    if (statusFilter !== "ALL" && t.processing_status !== statusFilter) {
      return false;
    }
    if (searchQuery.trim() !== "") {
      const q = searchQuery.trim().toLowerCase();
      const matchId = t.external_ticket_id.toLowerCase().includes(q);
      const matchSubj = t.subject.toLowerCase().includes(q);
      const matchErr = (t.last_error || "").toLowerCase().includes(q);
      if (!matchId && !matchSubj && !matchErr) {
        return false;
      }
    }
    return true;
  });
}

