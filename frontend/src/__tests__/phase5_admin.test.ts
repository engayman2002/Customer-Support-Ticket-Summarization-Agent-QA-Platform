import { describe, expect, it } from "vitest";
import {
  buildWebhookEndpointUrl,
  calculateFallbackRatePct,
  computeLatencyPercentiles,
  filterDlqTickets,
  formatTokenCount,
  maskEncryptedSecret,
  type DlqTicketSummary,
} from "../lib/admin-utils";

describe("Phase 5 — Admin Telemetry, DLQ & Integration Formatting Utilities", () => {
  it("computes p50, p95, p99 and average latency percentiles accurately", () => {
    const samples = [
      420, 460, 510, 530, 590, 610, 640, 680, 720, 790,
      810, 840, 870, 910, 950, 980, 1020, 1100, 1250, 1890,
    ];
    const stats = computeLatencyPercentiles(samples);
    expect(stats.p50_latency_ms).toBeGreaterThanOrEqual(790);
    expect(stats.p50_latency_ms).toBeLessThanOrEqual(810);
    expect(stats.p95_latency_ms).toBeGreaterThanOrEqual(1250);
    expect(stats.p99_latency_ms).toBeGreaterThanOrEqual(1750);
    expect(stats.avg_latency_ms).toBeGreaterThan(700);
    expect(stats.sample_size).toBe(20);

    const emptyStats = computeLatencyPercentiles([]);
    expect(emptyStats).toEqual({
      p50_latency_ms: 0,
      p95_latency_ms: 0,
      p99_latency_ms: 0,
      avg_latency_ms: 0,
      sample_size: 0,
    });
  });

  it("calculates model fallback percentage safely across zero and non-zero totals", () => {
    expect(calculateFallbackRatePct(8, 100)).toBe(8.0);
    expect(calculateFallbackRatePct(0, 100)).toBe(0);
    expect(calculateFallbackRatePct(0, 0)).toBe(0);
  });

  it("formats token counts and masks AES-256-GCM secrets cleanly", () => {
    expect(formatTokenCount(850)).toBe("850");
    expect(formatTokenCount(14500)).toBe("14,500");
    expect(formatTokenCount(2450000)).toBe("2.45M");

    const masked = maskEncryptedSecret("enc_aes256gcm_v1:9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c");
    expect(masked).toBe("enc_aes256gcm_v1:•••••••••••••••• (AES-256-GCM)");
    expect(maskEncryptedSecret("")).toBe("Not Configured");
  });

  it("builds multi-tenant webhook ingestion URLs and filters DLQ tickets", () => {
    const url = buildWebhookEndpointUrl(
      "ZENDESK",
      "22222222-2222-4222-8222-222222222201"
    );
    expect(url).toBe(
      "/api/v1/webhooks/zendesk/22222222-2222-4222-8222-222222222201"
    );

    const sampleDlq: DlqTicketSummary[] = [
      {
        ticket_id: "t-1",
        external_ticket_id: "ZD-5001",
        subject: "Rate limit exceeded during evaluation",
        processing_status: "FAILED_RETRYABLE",
        last_error: "Groq HTTP 503 Service Unavailable",
        updated_at: "2026-10-29T12:05:00Z",
      },
      {
        ticket_id: "t-2",
        external_ticket_id: "IC-9002",
        subject: "Empty customer transcript",
        processing_status: "FAILED_PERMANENT",
        last_error: "Transcript contains zero customer messages",
        updated_at: "2026-10-29T13:02:00Z",
      },
    ];

    expect(filterDlqTickets(sampleDlq, "ALL", "ZD-5001")).toHaveLength(1);
    expect(filterDlqTickets(sampleDlq, "FAILED_RETRYABLE", "")).toHaveLength(1);
    expect(filterDlqTickets(sampleDlq, "FAILED_PERMANENT", "")[0].external_ticket_id).toBe(
      "IC-9002"
    );
  });
});
