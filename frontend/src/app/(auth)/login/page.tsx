"use client";

import React, { useState } from "react";
import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";

interface SeededAccountPreset {
  label: string;
  roleBadge: string;
  email: string;
  password: string;
  description: string;
}

const SEEDED_ACCOUNTS: SeededAccountPreset[] = [
  {
    label: "Admin (Elena Vance)",
    roleBadge: "ADMIN",
    email: "admin@qa-platform.local",
    password: "Password123!",
    description: "Full access to /admin/integrations and /manager",
  },
  {
    label: "QA Manager (Marcus Sterling)",
    roleBadge: "MANAGER",
    email: "manager@qa-platform.local",
    password: "Password123!",
    description: "Access to /manager team analytics & QA evaluations",
  },
  {
    label: "Agent 1 (Sarah Jenkins)",
    roleBadge: "AGENT",
    email: "sarah.agent@qa-platform.local",
    password: "Password123!",
    description: "Assigned ZD-99412 + 1 unread manager coaching item",
  },
  {
    label: "Agent 2 (Omar Hassan)",
    roleBadge: "AGENT",
    email: "omar.agent@qa-platform.local",
    password: "Password123!",
    description: "Isolated agent workspace (0 assigned tickets)",
  },
];

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("manager@qa-platform.local");
  const [password, setPassword] = useState("Password123!");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      const result = await signIn("credentials", {
        email,
        password,
        redirect: false,
      });

      if (!result || result.error) {
        setError("Invalid email or password, or account is inactive.");
        setIsSubmitting(false);
        return;
      }

      router.push("/");
      router.refresh();
    } catch {
      setError("Authentication request failed. Please try again.");
      setIsSubmitting(false);
    }
  }

  function handleQuickFill(preset: SeededAccountPreset) {
    setEmail(preset.email);
    setPassword(preset.password);
    setError(null);
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-slate-950 px-4 py-12">
      <div className="w-full max-w-4xl grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        {/* Left Column: Credentials Sign-In Card */}
        <section className="lg:col-span-7 bg-slate-900/90 border border-slate-800 rounded-2xl p-8 shadow-2xl">
          <div className="mb-6">
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold tracking-wide uppercase bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              Phase 1 • Unified HS256 RBAC Auth
            </span>
            <h1 className="mt-3 text-2xl font-bold text-white">
              Support Ticket Summarization &amp; Agent QA
            </h1>
            <p className="mt-1 text-sm text-slate-400">
              Sign in with your platform credentials to mint a cross-service
              HS256 session token shared between Next.js 15 and FastAPI.
            </p>
          </div>

          {error && (
            <div
              role="alert"
              className="mb-6 rounded-lg bg-rose-500/10 border border-rose-500/30 px-4 py-3 text-sm text-rose-300"
            >
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label
                htmlFor="email"
                className="block text-xs font-semibold uppercase tracking-wider text-slate-300 mb-2"
              >
                Work Email
              </label>
              <input
                id="email"
                name="email"
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-lg bg-slate-950 border border-slate-700 px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
                placeholder="name@qa-platform.local"
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="block text-xs font-semibold uppercase tracking-wider text-slate-300 mb-2"
              >
                Password
              </label>
              <input
                id="password"
                name="password"
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-lg bg-slate-950 border border-slate-700 px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
                placeholder="••••••••••••"
              />
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-60 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-600/20 transition"
            >
              {isSubmitting
                ? "Verifying Credentials & Minting HS256 JWT..."
                : "Sign In to Workspace"}
            </button>
          </form>
        </section>

        {/* Right Column: Seeded Accounts Quick-Fill Panel */}
        <aside className="lg:col-span-5 bg-slate-900/60 border border-slate-800 rounded-2xl p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
            Seeded Verification Accounts
          </h2>
          <p className="mt-1 text-xs text-slate-400">
            Click any account below to pre-fill credentials (all seeded with{" "}
            <code className="text-indigo-300 font-mono">Password123!</code>):
          </p>

          <div className="mt-4 space-y-3">
            {SEEDED_ACCOUNTS.map((preset) => {
              const isSelected = email === preset.email;
              return (
                <button
                  key={preset.email}
                  type="button"
                  onClick={() => handleQuickFill(preset)}
                  className={`w-full text-left rounded-xl p-3.5 border transition ${
                    isSelected
                      ? "bg-indigo-950/50 border-indigo-500/60"
                      : "bg-slate-950/60 border-slate-800 hover:border-slate-700"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-white">
                      {preset.label}
                    </span>
                    <span className="text-[11px] font-mono font-semibold px-2 py-0.5 rounded bg-slate-800 text-indigo-300 border border-slate-700">
                      {preset.roleBadge}
                    </span>
                  </div>
                  <div className="mt-1 text-xs font-mono text-slate-300">
                    {preset.email}
                  </div>
                  <div className="mt-1 text-xs text-slate-400">
                    {preset.description}
                  </div>
                </button>
              );
            })}
          </div>
        </aside>
      </div>
    </main>
  );
}

