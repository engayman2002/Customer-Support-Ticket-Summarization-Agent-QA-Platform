export type ScoreBadgeVariant = "emerald" | "amber" | "rose";

export type ResolutionStatusType =
  | "RESOLVED"
  | "UNRESOLVED"
  | "PARTIALLY_RESOLVED"
  | "PREMATURELY_CLOSED"
  | "ESCALATED_PROPERLY";

export type EvidenceIssueType =
  | "POOR_TONE"
  | "PREMATURE_CLOSURE"
  | "UNHELPFUL_RESPONSE"
  | "IGNORED_QUESTION";

export type CoachingPriorityType = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export type FeedbackReadStatusType = "UNREAD" | "READ" | "ACKNOWLEDGED" | "NONE";

export interface FlaggedEvidenceQuoteItem {
  speaker: "AGENT" | "CUSTOMER" | string;
  quote: string;
  issue_type: EvidenceIssueType | string;
}

export interface TranscriptTextSegment {
  text: string;
  matchedQuote?: FlaggedEvidenceQuoteItem;
}

export interface FeedbackActionItem {
  id: string;
  description: string;
  completed: boolean;
}

export type TicketQuickPreset =
  | "ALL"
  | "PREMATURE_CLOSURES"
  | "LOW_SCORE"
  | "PENDING_FEEDBACK";

export interface TicketFilterParams {
  page?: number;
  limit?: number;
  resolutionStatus?: string;
  minScore?: number;
  maxScore?: number;
  prematureClosureOnly?: boolean;
  pendingFeedbackOnly?: boolean;
  agentId?: string;
  search?: string;
}

/**
 * Determine semantic color variant for a 0-100 QA score:
 * - >= 80: "emerald"
 * - 60..79: "amber"
 * - < 60: "rose"
 */
export function getScoreBadgeVariant(score: number | null | undefined): ScoreBadgeVariant {
  const numeric = typeof score === "number" && !Number.isNaN(score) ? score : 0;
  if (numeric >= 80) {
    return "emerald";
  }
  if (numeric >= 60) {
    return "amber";
  }
  return "rose";
}

export function getScoreBadgeClasses(score: number | null | undefined): string {
  const variant = getScoreBadgeVariant(score);
  if (variant === "emerald") {
    return "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
  }
  if (variant === "amber") {
    return "bg-amber-500/15 text-amber-300 border-amber-500/30";
  }
  return "bg-rose-500/15 text-rose-300 border-rose-500/30";
}

export function getResolutionBadgeClasses(status: string | null | undefined): string {
  const normalized = (status || "").toUpperCase();
  if (normalized === "RESOLVED" || normalized === "ESCALATED_PROPERLY") {
    return "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
  }
  if (normalized === "PARTIALLY_RESOLVED") {
    return "bg-amber-500/15 text-amber-300 border-amber-500/30";
  }
  if (normalized === "PREMATURELY_CLOSED" || normalized === "UNRESOLVED") {
    return "bg-rose-500/15 text-rose-300 border-rose-500/30";
  }
  return "bg-slate-800 text-slate-300 border-slate-700";
}

export function getFeedbackStatusBadgeClasses(status: string | null | undefined): string {
  const normalized = (status || "NONE").toUpperCase();
  if (normalized === "ACKNOWLEDGED") {
    return "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
  }
  if (normalized === "READ") {
    return "bg-sky-500/15 text-sky-300 border-sky-500/30";
  }
  if (normalized === "UNREAD") {
    return "bg-amber-500/15 text-amber-300 border-amber-500/30";
  }
  return "bg-slate-800/80 text-slate-400 border-slate-700";
}

export function getCoachingPriorityBadgeClasses(priority: string | null | undefined): string {
  const normalized = (priority || "MEDIUM").toUpperCase();
  if (normalized === "CRITICAL" || normalized === "HIGH") {
    return "bg-rose-500/15 text-rose-300 border-rose-500/30";
  }
  if (normalized === "MEDIUM") {
    return "bg-amber-500/15 text-amber-300 border-amber-500/30";
  }
  return "bg-indigo-500/15 text-indigo-300 border-indigo-500/30";
}

export function formatSentimentTrajectory(trajectory: string | null | undefined): {
  label: string;
  classes: string;
} {
  const normalized = (trajectory || "").toUpperCase();
  switch (normalized) {
    case "IMPROVED":
      return {
        label: "↗ Improved",
        classes: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25",
      };
    case "UNCHANGED_POSITIVE":
      return {
        label: "→ Positive",
        classes: "bg-sky-500/10 text-sky-300 border-sky-500/25",
      };
    case "UNCHANGED_NEGATIVE":
      return {
        label: "→ Negative",
        classes: "bg-amber-500/10 text-amber-300 border-amber-500/25",
      };
    case "DEGRADED":
      return {
        label: "↘ Degraded",
        classes: "bg-rose-500/10 text-rose-300 border-rose-500/25",
      };
    default:
      return {
        label: normalized || "Unknown",
        classes: "bg-slate-800 text-slate-400 border-slate-700",
      };
  }
}

export function getIssueTypeHighlightStyle(issueType: string | null | undefined): {
  severity: "rose" | "amber";
  highlightClass: string;
  badgeClass: string;
} {
  const normalized = (issueType || "").toUpperCase();
  if (normalized === "PREMATURE_CLOSURE" || normalized === "POOR_TONE") {
    return {
      severity: "rose",
      highlightClass:
        "bg-rose-500/20 text-rose-100 border-b-2 border-rose-400 px-1 py-0.5 rounded",
      badgeClass:
        "bg-rose-500/25 text-rose-200 border border-rose-500/40",
    };
  }
  return {
    severity: "amber",
    highlightClass:
      "bg-amber-500/20 text-amber-100 border-b-2 border-amber-400 px-1 py-0.5 rounded",
    badgeClass:
      "bg-amber-500/25 text-amber-200 border border-amber-500/40",
  };
}

/**
 * Split a transcript message body into ordered segments, highlighting any verbatim
 * substring that matches `flaggedEvidenceQuotes` without corrupting non-matching text.
 */
export function highlightTranscriptText(
  content: string,
  flaggedQuotes: FlaggedEvidenceQuoteItem[] | null | undefined
): TranscriptTextSegment[] {
  if (!content) {
    return [{ text: "" }];
  }
  const validQuotes = (flaggedQuotes || []).filter(
    (q) => q && typeof q.quote === "string" && q.quote.trim().length > 0
  );
  if (validQuotes.length === 0) {
    return [{ text: content }];
  }

  let segments: TranscriptTextSegment[] = [{ text: content }];

  for (const quoteObj of validQuotes) {
    const needle = quoteObj.quote.trim();
    const lowerNeedle = needle.toLowerCase();
    const nextSegments: TranscriptTextSegment[] = [];

    for (const seg of segments) {
      if (seg.matchedQuote) {
        nextSegments.push(seg);
        continue;
      }

      const haystack = seg.text;
      const lowerHaystack = haystack.toLowerCase();
      let cursor = 0;
      let matchIdx = lowerHaystack.indexOf(lowerNeedle, cursor);

      if (matchIdx === -1) {
        nextSegments.push(seg);
        continue;
      }

      while (matchIdx !== -1) {
        if (matchIdx > cursor) {
          nextSegments.push({
            text: haystack.slice(cursor, matchIdx),
          });
        }
        nextSegments.push({
          text: haystack.slice(matchIdx, matchIdx + needle.length),
          matchedQuote: quoteObj,
        });
        cursor = matchIdx + needle.length;
        matchIdx = lowerHaystack.indexOf(lowerNeedle, cursor);
      }

      if (cursor < haystack.length) {
        nextSegments.push({
          text: haystack.slice(cursor),
        });
      }
    }

    segments = nextSegments;
  }

  return segments;
}

/**
 * Apply one of the 4 Quick Filter Presets from Section 6.3:
 * - "ALL": clears preset filters
 * - "PREMATURE_CLOSURES": sets resolutionStatus="PREMATURELY_CLOSED", prematureClosureOnly=true
 * - "LOW_SCORE": sets maxScore=59
 * - "PENDING_FEEDBACK": sets pendingFeedbackOnly=true
 */
export function applyTicketFilterPreset(
  preset: TicketQuickPreset,
  current: TicketFilterParams = {}
): TicketFilterParams {
  const base: TicketFilterParams = {
    page: 1,
    limit: current.limit ?? 25,
    agentId: current.agentId,
    search: current.search,
  };

  switch (preset) {
    case "PREMATURE_CLOSURES":
      return {
        ...base,
        resolutionStatus: "PREMATURELY_CLOSED",
        prematureClosureOnly: true,
      };
    case "LOW_SCORE":
      return {
        ...base,
        maxScore: 59,
      };
    case "PENDING_FEEDBACK":
      return {
        ...base,
        pendingFeedbackOnly: true,
      };
    case "ALL":
    default:
      return base;
  }
}

/**
 * Serialize `TicketFilterParams` into a clean URL query string (omitting undefined/empty values).
 */
export function buildTicketFilterQueryString(params: TicketFilterParams): string {
  const searchParams = new URLSearchParams();

  if (params.page && params.page > 0) {
    searchParams.set("page", String(params.page));
  }
  if (params.limit && params.limit > 0) {
    searchParams.set("limit", String(params.limit));
  }
  if (params.resolutionStatus && params.resolutionStatus.trim() !== "") {
    searchParams.set("resolutionStatus", params.resolutionStatus.trim());
  }
  if (typeof params.minScore === "number" && !Number.isNaN(params.minScore)) {
    searchParams.set("minScore", String(params.minScore));
  }
  if (typeof params.maxScore === "number" && !Number.isNaN(params.maxScore)) {
    searchParams.set("maxScore", String(params.maxScore));
  }
  if (params.prematureClosureOnly === true) {
    searchParams.set("prematureClosureOnly", "true");
  }
  if (params.pendingFeedbackOnly === true) {
    searchParams.set("pendingFeedbackOnly", "true");
  }
  if (params.agentId && params.agentId.trim() !== "") {
    searchParams.set("agentId", params.agentId.trim());
  }
  if (params.search && params.search.trim() !== "") {
    searchParams.set("search", params.search.trim());
  }

  return searchParams.toString();
}

/**
 * Strict Agent Inbox Completion Gate (Section 6.4):
 * Returns `true` ONLY when every item in `actionItems` has been checked (`completedIds` contains its `id`
 * or `item.completed === true`). If a feedback item has 0 action items, returns `true`.
 */
export function canAcknowledgeFeedback(
  actionItems: FeedbackActionItem[] | null | undefined,
  completedIds?: Set<string> | string[]
): boolean {
  const items = actionItems || [];
  if (items.length === 0) {
    return true;
  }

  const completedSet =
    completedIds instanceof Set
      ? completedIds
      : Array.isArray(completedIds)
        ? new Set(completedIds)
        : null;

  return items.every((item) => {
    if (completedSet !== null) {
      return completedSet.has(item.id);
    }
    return Boolean(item.completed);
  });
}

/**
 * Build the exact Section 5.2 `PATCH /api/v1/feedback/{id}/status` request payload.
 */
export function buildFeedbackStatusPatchPayload(params: {
  readStatus: "READ" | "ACKNOWLEDGED";
  completedActionItemIds?: string[];
  agentAcknowledgementNote?: string;
}): {
  read_status: "READ" | "ACKNOWLEDGED";
  completed_action_item_ids?: string[];
  agent_acknowledgement_note?: string;
} {
  const payload: {
    read_status: "READ" | "ACKNOWLEDGED";
    completed_action_item_ids?: string[];
    agent_acknowledgement_note?: string;
  } = {
    read_status: params.readStatus,
  };

  if (params.completedActionItemIds) {
    payload.completed_action_item_ids = [...params.completedActionItemIds];
  }
  if (
    typeof params.agentAcknowledgementNote === "string" &&
    params.agentAcknowledgementNote.trim().length > 0
  ) {
    payload.agent_acknowledgement_note = params.agentAcknowledgementNote.trim();
  }

  return payload;
}

