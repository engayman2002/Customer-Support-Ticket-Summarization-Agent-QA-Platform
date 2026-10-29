"use client";

import React, { useEffect, useState } from "react";

interface BackendAuthVerifierProps {
  accessToken: string;
  initialServerMeResponse?: Record<string, unknown> | null;
  apiBaseUrl?: string;
}

export function BackendAuthVerifier({
  accessToken,
  initialServerMeResponse = null,
  apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000",
}: BackendAuthVerifierProps) {
  const [meResult, setMeResult] = useState<Record<string, unknown> | null>(
    initialServerMeResponse
  );
  const [meStatus, setMeStatus] = useState<number | null>(
    initialServerMeResponse ? 200 : null
  );
  const [rbacCheckStatus, setRbacCheckStatus] = useState<number | null>(null);
  const [rbacCheckBody, setRbacCheckBody] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);

  async function verifyFastApiEndpoints() {
    if (!accessToken) {
      return;
    }
    setIsLoading(true);
    setFetchError(null);

    try {
      const [meRes, rbacRes] = await Promise.all([
        fetch(`${apiBaseUrl}/api/v1/auth/me`, {
          headers: {
            Authorization: `Bearer ${accessToken}`,
          },
        }),
        fetch(`${apiBaseUrl}/api/v1/manager/rbac-check`, {
          headers: {
            Authorization: `Bearer ${accessToken}`,
          },
        }),
      ]);

      setMeStatus(meRes.status);
      const meJson = (await meRes.json()) as Record<string, unknown>;
      setMeResult(meJson);

      setRbacCheckStatus(rbacRes.status);
      const rbacJson = (await rbacRes.json()) as Record<string, unknown>;
      setRbacCheckBody(rbacJson);
    } catch (err) {
      setFetchError(
        err instanceof Error
          ? `FastAPI connection note (${apiBaseUrl}): ${err.message}`
          : "FastAPI connection error"
      );
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void verifyFastApiEndpoints();
  }, [accessToken]);

  return (
    <section className="rounded-xl bg-slate-900 border border-slate-800 p-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-white">
            Cross-Service HS256 JWT Verification (`GET /api/v1/auth/me`)
          </h2>
          <p className="text-xs text-slate-400">
            Verifies `session.accessToken` signed by Next.js (Auth.js v5)
            directly against FastAPI (`backend/app/core/security.py`).
          </p>
        </div>

        <button
          type="button"
          onClick={() => void verifyFastApiEndpoints()}
          disabled={isLoading}
          className="rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/40 px-3.5 py-1.5 text-xs font-semibold text-indigo-300 transition"
        >
          {isLoading ? "Checking FastAPI..." : "Re-Verify FastAPI Token"}
        </button>
      </div>

      {fetchError && (
        <div className="rounded-lg bg-amber-500/10 border border-amber-500/30 px-4 py-2.5 text-xs text-amber-300">
          {fetchError}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-lg bg-slate-950 border border-slate-800 p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-mono text-slate-400">
              GET /api/v1/auth/me
            </span>
            {meStatus !== null && (
              <span
                className={`text-xs font-mono px-2 py-0.5 rounded ${
                  meStatus === 200
                    ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                    : "bg-rose-500/15 text-rose-300 border border-rose-500/30"
                }`}
              >
                HTTP {meStatus}
              </span>
            )}
          </div>
          <pre className="text-xs font-mono text-slate-200 overflow-x-auto">
            {meResult
              ? JSON.stringify(meResult, null, 2)
              : "Awaiting FastAPI response..."}
          </pre>
        </div>

        <div className="rounded-lg bg-slate-950 border border-slate-800 p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-mono text-slate-400">
              GET /api/v1/manager/rbac-check
            </span>
            {rbacCheckStatus !== null && (
              <span
                className={`text-xs font-mono px-2 py-0.5 rounded ${
                  rbacCheckStatus === 200
                    ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                    : "bg-amber-500/15 text-amber-300 border border-amber-500/30"
                }`}
              >
                HTTP {rbacCheckStatus}
              </span>
            )}
          </div>
          <pre className="text-xs font-mono text-slate-200 overflow-x-auto">
            {rbacCheckBody
              ? JSON.stringify(rbacCheckBody, null, 2)
              : "Awaiting FastAPI RBAC check..."}
          </pre>
        </div>
      </div>

      <div className="rounded-lg bg-slate-950 border border-slate-800 p-3">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-1">
          Minted HS256 JWS `session.accessToken`
        </div>
        <code className="block text-[11px] font-mono text-indigo-300 break-all">
          {accessToken}
        </code>
      </div>
    </section>
  );
}

