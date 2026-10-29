import React from "react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { auth, signOut } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

  let unreadCount = 0;
  if (session.user.role === "AGENT") {
    try {
      unreadCount = await prisma.managerFeedback.count({
        where: {
          agentId: session.user.id,
          readStatus: "UNREAD",
        },
      });
    } catch {
      unreadCount = 0;
    }
  }

  async function handleSignOut() {
    "use server";
    await signOut({ redirectTo: "/login" });
  }

  const isManagerOrAdmin =
    session.user.role === "MANAGER" || session.user.role === "ADMIN";

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <header className="border-b border-slate-800 bg-slate-900/85 backdrop-blur sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
          <div className="flex items-center gap-6">
            <Link
              href={isManagerOrAdmin ? "/manager" : "/agent"}
              className="text-sm font-bold tracking-tight text-white hover:text-indigo-300 transition"
            >
              Support QA &amp; Coaching Platform
            </Link>

            <nav className="hidden md:flex items-center gap-2 text-xs font-medium">
              {isManagerOrAdmin ? (
                <>
                  <Link
                    href="/manager"
                    className="px-3 py-1.5 rounded-lg bg-slate-800/70 hover:bg-slate-800 text-slate-200 transition"
                  >
                    Overview Analytics
                  </Link>
                  <Link
                    href="/manager/tickets"
                    className="px-3 py-1.5 rounded-lg bg-slate-800/70 hover:bg-slate-800 text-slate-200 transition"
                  >
                    Ticket QA Review
                  </Link>
                  <Link
                    href="/manager/agents"
                    className="px-3 py-1.5 rounded-lg bg-slate-800/70 hover:bg-slate-800 text-slate-200 transition"
                  >
                    Agent Leaderboard
                  </Link>
                  {session.user.role === "ADMIN" && (
                    <Link
                      href="/admin/integrations"
                      className="px-3 py-1.5 rounded-lg bg-indigo-500/15 hover:bg-indigo-500/25 border border-indigo-500/30 text-indigo-200 transition"
                    >
                      CRM Integrations
                    </Link>
                  )}
                </>
              ) : (
                <>
                  <Link
                    href="/agent"
                    className="px-3 py-1.5 rounded-lg bg-slate-800/70 hover:bg-slate-800 text-slate-200 transition"
                  >
                    My Performance
                  </Link>
                  <Link
                    href="/agent/inbox"
                    className="px-3 py-1.5 rounded-lg bg-slate-800/70 hover:bg-slate-800 text-slate-200 transition inline-flex items-center gap-2"
                  >
                    <span>Manager Feedback Inbox</span>
                    {unreadCount > 0 && (
                      <span className="px-1.5 py-0.5 rounded-full text-[10px] font-mono font-bold bg-rose-500 text-white">
                        {unreadCount}
                      </span>
                    )}
                  </Link>
                  <Link
                    href="/agent/coaching"
                    className="px-3 py-1.5 rounded-lg bg-slate-800/70 hover:bg-slate-800 text-slate-200 transition"
                  >
                    AI Coaching History
                  </Link>
                </>
              )}
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
