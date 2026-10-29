import React from "react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { auth, signOut } from "@/lib/auth";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

  async function handleSignOut() {
    "use server";
    await signOut({ redirectTo: "/login" });
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
          <div className="flex items-center gap-6">
            <span className="text-sm font-bold tracking-tight text-white">
              Support QA &amp; Coaching Platform
            </span>
            <nav className="hidden md:flex items-center gap-3 text-xs font-medium">
              <Link
                href="/manager"
                className="px-3 py-1.5 rounded-lg bg-slate-800/70 hover:bg-slate-800 text-slate-200 transition"
              >
                Manager Dashboard (/manager)
              </Link>
              <Link
                href="/agent"
                className="px-3 py-1.5 rounded-lg bg-slate-800/70 hover:bg-slate-800 text-slate-200 transition"
              >
                Agent Workspace (/agent)
              </Link>
              <Link
                href="/admin/integrations"
                className="px-3 py-1.5 rounded-lg bg-slate-800/70 hover:bg-slate-800 text-slate-200 transition"
              >
                Admin Integrations (/admin/integrations)
              </Link>
            </nav>
          </div>

          <div className="flex items-center gap-4">
            <div className="text-right">
              <div className="text-xs font-semibold text-white">
                {session.user.fullName || session.user.email}
              </div>
              <div className="text-[11px] font-mono text-indigo-400">
                Role: {session.user.role}
              </div>
            </div>

            <form action={handleSignOut}>
              <button
                type="submit"
                className="rounded-lg bg-rose-600/20 hover:bg-rose-600/30 border border-rose-500/30 px-3.5 py-1.5 text-xs font-semibold text-rose-200 transition"
              >
                Sign Out
              </button>
            </form>
          </div>
        </div>
      </header>

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {children}
      </main>
    </div>
  );
}

