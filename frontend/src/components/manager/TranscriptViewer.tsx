import React from "react";
import type { TranscriptMessageTurn } from "@/lib/api-client";
import {
  type FlaggedEvidenceQuoteItem,
  getIssueTypeHighlightStyle,
  highlightTranscriptText,
} from "@/lib/dashboard-utils";

export function TranscriptViewer({
  turns,
  flaggedQuotes,
}: {
  turns: TranscriptMessageTurn[];
  flaggedQuotes: FlaggedEvidenceQuoteItem[];
}) {
  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 flex flex-col h-full">
      <div className="border-b border-slate-800 px-4 py-3.5 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-bold text-white">
            Conversation Transcript
          </h2>
          <p className="text-[11px] text-slate-400">
            {turns.length} chronological turns • Flagged evidence quotes
            highlighted inline
          </p>
        </div>
        {flaggedQuotes.length > 0 && (
          <span className="px-2 py-0.5 rounded-full text-[11px] font-mono font-semibold bg-rose-500/15 text-rose-300 border border-rose-500/30">
            {flaggedQuotes.length} Flagged Evidence{" "}
            {flaggedQuotes.length === 1 ? "Quote" : "Quotes"}
          </span>
        )}
      </div>

      <div className="p-4 space-y-4 overflow-y-auto max-h-[760px]">
        {turns.length === 0 ? (
          <div className="text-sm text-slate-400 py-8 text-center">
            No transcript turns recorded for this ticket.
          </div>
        ) : (
          turns.map((turn, idx) => {
            const roleUpper = (turn.sender_role || "CUSTOMER").toUpperCase();
            const isAgent = roleUpper === "AGENT";
            const isSystem = roleUpper === "SYSTEM" || roleUpper === "BOT";
            const segments = highlightTranscriptText(
              turn.content || "",
              flaggedQuotes
            );
            const hasFlaggedSegment = segments.some((s) =>
              Boolean(s.matchedQuote)
            );

            return (
              <div
                key={turn.message_id || `turn-${idx}`}
                className={`rounded-xl p-3.5 border transition ${
                  hasFlaggedSegment
                    ? "bg-rose-950/20 border-rose-500/40"
                    : isAgent
                      ? "bg-indigo-950/25 border-indigo-500/25 ml-3"
                      : isSystem
                        ? "bg-slate-950/60 border-slate-800 text-xs"
                        : "bg-slate-950 border-slate-800 mr-3"
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5">
                  <div className="flex items-center gap-2">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase ${
                        isAgent
                          ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30"
                          : isSystem
                            ? "bg-slate-800 text-slate-400"
                            : "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                      }`}
                    >
                      {roleUpper}
                    </span>
                    {turn.sender_name && (
                      <span className="text-xs font-semibold text-slate-200">
                        {turn.sender_name}
                      </span>
                    )}
                    <span className="text-[11px] font-mono text-slate-500">
                      Turn #{idx + 1}
                    </span>
                  </div>

                  {turn.timestamp && (
                    <span className="text-[11px] font-mono text-slate-400">
                      {new Date(turn.timestamp).toLocaleString("en-US", {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  )}
                </div>

                <div className="text-sm text-slate-200 leading-relaxed whitespace-pre-wrap">
                  {segments.map((seg, sIdx) => {
                    if (!seg.matchedQuote) {
                      return <span key={sIdx}>{seg.text}</span>;
                    }
                    const style = getIssueTypeHighlightStyle(
                      seg.matchedQuote.issue_type
                    );
                    return (
                      <span
                        key={sIdx}
                        className="inline-block my-0.5"
                        title={`Flagged ${seg.matchedQuote.issue_type} (${seg.matchedQuote.speaker})`}
                      >
                        <mark className={style.highlightClass}>{seg.text}</mark>
                        <span
                          className={`ml-1.5 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono font-bold uppercase align-middle ${style.badgeClass}`}
                        >
                          ⚠ {seg.matchedQuote.issue_type}
                        </span>
                      </span>
                    );
                  })}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

