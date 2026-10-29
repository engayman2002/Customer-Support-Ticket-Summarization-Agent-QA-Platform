import { prisma } from "@/lib/prisma";
import {
  type FeedbackActionItem,
  type FlaggedEvidenceQuoteItem,
  type TicketFilterParams,
  buildTicketFilterQueryString,
} from "@/lib/dashboard-utils";

export interface ManagerAnalyticsOverviewData {
  kpis: {
    total_tickets_evaluated: number;
    average_agent_score: number;
    proper_resolution_rate_pct: number;
    premature_closure_rate_pct: number;
    avg_empathy_rating: number;
    unreviewed_low_score_tickets_count: number;
  };
  score_trend_daily: Array<{
    date: string;
    avg_score: number;
    premature_closures: number;
    total_tickets: number;
  }>;
  issue_category_breakdown: Array<{
    category: string;
    count: number;
    avg_score: number;
  }>;
  agent_risk_matrix: Array<{
    agent_id: string;
    full_name: string;
    email: string;
    evaluated_tickets: number;
    average_agent_score: number;
    proper_resolution_rate_pct: number;
    premature_closure_rate_pct: number;
    avg_empathy_rating: number;
  }>;
}

export interface TicketReviewRow {
  ticket_id: string;
  external_ticket_id: string;
  subject: string;
  channel: string;
  priority: string;
  processing_status: string;
  assigned_agent: {
    id: string;
    full_name: string;
    email: string;
  };
  ticket_closed_at: string | null;
  ai_qa_summary: {
    agent_score: number;
    resolution_status: string;
    is_resolved_properly: boolean;
    premature_closure_detected: boolean;
    empathy_rating: number;
    clarity_and_accuracy_rating?: number;
    ownership_and_efficiency_rating?: number;
    issue_category: string;
    customer_sentiment_trajectory: string;
  } | null;
  feedback_status: string;
}

export interface PaginatedTicketsResponse {
  data: TicketReviewRow[];
  pagination: {
    page: number;
    limit: number;
    total_records: number;
    total_pages: number;
  };
}

export interface CoachingPlanItemData {
  focus_area: string;
  specific_action: string;
  suggested_phrasing_example: string;
}

export interface AiQaReportDetailData {
  id: string;
  ticket_id: string;
  summary: string;
  core_issue: string;
  issue_category: string;
  resolution_status: string;
  is_resolved_properly: boolean;
  premature_closure_detected: boolean;
  premature_closure_reason: string | null;
  agent_score: number;
  empathy_rating: number;
  clarity_and_accuracy_rating: number;
  ownership_and_efficiency_rating: number;
  customer_sentiment_trajectory: string;
  strengths: string[];
  areas_for_improvement: string[];
  flagged_evidence_quotes: FlaggedEvidenceQuoteItem[];
  actionable_coaching_plan: CoachingPlanItemData[];
  model_used: string;
  prompt_tokens: number;
  completion_tokens: number;
  inference_latency_ms: number;
  evaluated_at: string | null;
}

export interface ManagerFeedbackItemData {
  id: string;
  ticket_id: string;
  manager_id: string;
  manager: {
    id: string;
    full_name: string;
    email: string;
  } | null;
  agent_id: string;
  manager_override_score: number | null;
  coaching_priority: string;
  comments: string;
  action_items: FeedbackActionItem[];
  read_status: string;
  agent_acknowledgement_note: string | null;
  read_at: string | null;
  acknowledged_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  ticket?: {
    ticket_id: string;
    external_ticket_id: string;
    subject: string;
    ticket_closed_at: string | null;
    ai_agent_score: number | null;
    resolution_status: string | null;
  } | null;
}

export interface TranscriptMessageTurn {
  message_id?: string;
  sender_role: string;
  sender_name?: string;
  timestamp?: string;
  content: string;
  is_internal_note?: boolean;
}

export interface TicketDetailResponse {
  ticket_id: string;
  external_ticket_id: string;
  integration_id: string;
  subject: string;
  channel: string;
  priority: string;
  processing_status: string;
  customer_identifier: string;
  first_response_time_seconds: number | null;
  total_resolution_time_seconds: number | null;
  ticket_created_at: string | null;
  ticket_closed_at: string | null;
  assigned_agent: {
    id: string;
    full_name: string;
    email: string;
  };
  raw_transcript: TranscriptMessageTurn[];
  ticket_metadata: Record<string, unknown>;
  ai_qa_report: AiQaReportDetailData | null;
  manager_feedbacks: ManagerFeedbackItemData[];
}

export interface AgentPersonalSummaryData {
  agent: {
    id: string;
    email: string;
    full_name: string;
  };
  kpis: {
    total_tickets_evaluated: number;
    average_agent_score: number;
    proper_resolution_rate_pct: number;
    premature_closure_rate_pct: number;
    avg_empathy_rating: number;
    avg_clarity_rating: number;
    avg_ownership_rating: number;
    unread_feedback_count: number;
    high_priority_unread_count: number;
  };
  score_trend_daily: Array<{
    date: string;
    avg_score: number;
    total_tickets: number;
  }>;
  recent_coaching_plans: Array<{
    ticket_id: string;
    external_ticket_id: string;
    subject: string;
    ticket_closed_at: string | null;
    agent_score: number;
    resolution_status: string;
    issue_category: string;
    strengths: string[];
    areas_for_improvement: string[];
    actionable_coaching_plan: CoachingPlanItemData[];
  }>;
}

function getFastApiBaseUrl(): string {
  return (
    process.env.FASTAPI_INTERNAL_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000"
  );
}

async function tryFetchFastApi<T>(
  path: string,
  accessToken: string,
  init?: RequestInit
): Promise<T | null> {
  if (!accessToken) {
    return null;
  }
  const baseUrl = getFastApiBaseUrl();
  try {
    const res = await fetch(`${baseUrl}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${accessToken}`,
        ...(init?.headers || {}),
      },
      cache: "no-store",
    });
    if (!res.ok) {
      return null;
    }
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

/**
 * Dual-Mode Manager Analytics Overview:
 * Attempts FastAPI (`GET /api/v1/manager/analytics/overview`) and falls back to Prisma.
 */
export async function fetchManagerAnalyticsOverview(
  accessToken: string
): Promise<ManagerAnalyticsOverviewData> {
  const fastApiData = await tryFetchFastApi<ManagerAnalyticsOverviewData>(
    "/api/v1/manager/analytics/overview",
    accessToken
  );
  if (fastApiData && fastApiData.kpis) {
    return fastApiData;
  }

  const tickets = await prisma.ticket.findMany({
    where: {
      aiQaReport: {
        isNot: null,
      },
    },
    include: {
      aiQaReport: true,
      assignedAgent: true,
      managerFeedbacks: true,
    },
    orderBy: {
      ticketClosedAt: "asc",
    },
  });

  const totalEvaluated = tickets.length;
  if (totalEvaluated === 0) {
    return {
      kpis: {
        total_tickets_evaluated: 0,
        average_agent_score: 0,
        proper_resolution_rate_pct: 0,
        premature_closure_rate_pct: 0,
        avg_empathy_rating: 0,
        unreviewed_low_score_tickets_count: 0,
      },
      score_trend_daily: [],
      issue_category_breakdown: [],
      agent_risk_matrix: [],
    };
  }

  let totalScore = 0;
  let properCount = 0;
  let prematureCount = 0;
  let totalEmpathy = 0;
  let unreviewedLowScore = 0;

  const dailyMap = new Map<
    string,
    { scoreSum: number; prematureClosures: number; totalTickets: number }
  >();
  const categoryMap = new Map<string, { count: number; scoreSum: number }>();
  const agentMap = new Map<
    string,
    {
      agent_id: string;
      full_name: string;
      email: string;
      totalTickets: number;
      scoreSum: number;
      empathySum: number;
      prematureClosures: number;
      properResolutions: number;
    }
  >();

  for (const tkt of tickets) {
    const rep = tkt.aiQaReport;
    if (!rep) continue;

    totalScore += rep.agentScore;
    totalEmpathy += rep.empathyRating;
    if (rep.isResolvedProperly) properCount += 1;
    if (rep.prematureClosureDetected) prematureCount += 1;
    if (rep.agentScore < 60 && tkt.managerFeedbacks.length === 0) {
      unreviewedLowScore += 1;
    }

    const dayKey = tkt.ticketClosedAt.toISOString().slice(0, 10);
    const dayBucket = dailyMap.get(dayKey) || {
      scoreSum: 0,
      prematureClosures: 0,
      totalTickets: 0,
    };
    dayBucket.scoreSum += rep.agentScore;
    dayBucket.totalTickets += 1;
    if (rep.prematureClosureDetected) dayBucket.prematureClosures += 1;
    dailyMap.set(dayKey, dayBucket);

    const catKey = String(rep.issueCategory);
    const catBucket = categoryMap.get(catKey) || { count: 0, scoreSum: 0 };
    catBucket.count += 1;
    catBucket.scoreSum += rep.agentScore;
    categoryMap.set(catKey, catBucket);

    const agId = tkt.assignedAgentId;
    const agBucket = agentMap.get(agId) || {
      agent_id: agId,
      full_name: tkt.assignedAgent.fullName,
      email: tkt.assignedAgent.email,
      totalTickets: 0,
      scoreSum: 0,
      empathySum: 0,
      prematureClosures: 0,
      properResolutions: 0,
    };
    agBucket.totalTickets += 1;
    agBucket.scoreSum += rep.agentScore;
    agBucket.empathySum += rep.empathyRating;
    if (rep.prematureClosureDetected) agBucket.prematureClosures += 1;
    if (rep.isResolvedProperly) agBucket.properResolutions += 1;
    agentMap.set(agId, agBucket);
  }

  const score_trend_daily = Array.from(dailyMap.entries()).map(([date, b]) => ({
    date,
    avg_score: Number((b.scoreSum / b.totalTickets).toFixed(1)),
    premature_closures: b.prematureClosures,
    total_tickets: b.totalTickets,
  }));

  const issue_category_breakdown = Array.from(categoryMap.entries())
    .map(([category, b]) => ({
      category,
      count: b.count,
      avg_score: Number((b.scoreSum / b.count).toFixed(1)),
    }))
    .sort((a, b) => b.count - a.count);

  const agent_risk_matrix = Array.from(agentMap.values())
    .map((ab) => ({
      agent_id: ab.agent_id,
      full_name: ab.full_name,
      email: ab.email,
      evaluated_tickets: ab.totalTickets,
      average_agent_score: Number((ab.scoreSum / ab.totalTickets).toFixed(1)),
      proper_resolution_rate_pct: Number(
        ((ab.properResolutions / ab.totalTickets) * 100).toFixed(1)
      ),
      premature_closure_rate_pct: Number(
        ((ab.prematureClosures / ab.totalTickets) * 100).toFixed(1)
      ),
      avg_empathy_rating: Number((ab.empathySum / ab.totalTickets).toFixed(1)),
    }))
    .sort(
      (a, b) =>
        b.premature_closure_rate_pct - a.premature_closure_rate_pct ||
        a.average_agent_score - b.average_agent_score
    );

  return {
    kpis: {
      total_tickets_evaluated: totalEvaluated,
      average_agent_score: Number((totalScore / totalEvaluated).toFixed(1)),
      proper_resolution_rate_pct: Number(
        ((properCount / totalEvaluated) * 100).toFixed(1)
      ),
      premature_closure_rate_pct: Number(
        ((prematureCount / totalEvaluated) * 100).toFixed(1)
      ),
      avg_empathy_rating: Number((totalEmpathy / totalEvaluated).toFixed(1)),
      unreviewed_low_score_tickets_count: unreviewedLowScore,
    },
    score_trend_daily,
    issue_category_breakdown,
    agent_risk_matrix,
  };
}

/**
 * Dual-Mode Paginated & Filterable Ticket Review Table List:
 * Attempts FastAPI (`GET /api/v1/tickets?...`) and falls back to Prisma.
 */
export async function fetchTicketsForReview(
  accessToken: string,
  params: TicketFilterParams
): Promise<PaginatedTicketsResponse> {
  const qs = buildTicketFilterQueryString(params);
  const fastApiRes = await tryFetchFastApi<PaginatedTicketsResponse>(
    `/api/v1/tickets${qs ? `?${qs}` : ""}`,
    accessToken
  );
  if (fastApiRes && Array.isArray(fastApiRes.data)) {
    return fastApiRes;
  }

  const allTickets = await prisma.ticket.findMany({
    include: {
      assignedAgent: true,
      aiQaReport: true,
      managerFeedbacks: {
        orderBy: {
          createdAt: "desc",
        },
      },
    },
    orderBy: {
      ticketClosedAt: "desc",
    },
  });

  const filtered = allTickets.filter((t) => {
    if (params.agentId && t.assignedAgentId !== params.agentId) {
      return false;
    }
    if (params.search && params.search.trim() !== "") {
      const q = params.search.trim().toLowerCase();
      const matchesId = t.externalTicketId.toLowerCase().includes(q);
      const matchesSubj = t.subject.toLowerCase().includes(q);
      if (!matchesId && !matchesSubj) {
        return false;
      }
    }
    if (params.resolutionStatus && params.resolutionStatus.trim() !== "") {
      if (
        String(t.aiQaReport?.resolutionStatus || "") !==
        params.resolutionStatus.trim()
      ) {
        return false;
      }
    }
    if (
      typeof params.minScore === "number" &&
      !Number.isNaN(params.minScore)
    ) {
      if ((t.aiQaReport?.agentScore ?? -1) < params.minScore) {
        return false;
      }
    }
    if (
      typeof params.maxScore === "number" &&
      !Number.isNaN(params.maxScore)
    ) {
      if ((t.aiQaReport?.agentScore ?? 999) > params.maxScore) {
        return false;
      }
    }
    if (params.prematureClosureOnly === true) {
      if (!t.aiQaReport?.prematureClosureDetected) {
        return false;
      }
    }
    if (params.pendingFeedbackOnly === true) {
      if (t.managerFeedbacks.length > 0) {
        return false;
      }
    }
    return true;
  });

  const page = Math.max(1, params.page ?? 1);
  const limit = Math.max(1, params.limit ?? 25);
  const totalRecords = filtered.length;
  const totalPages = Math.max(1, Math.ceil(totalRecords / limit));
  const slice = filtered.slice((page - 1) * limit, page * limit);

  const data: TicketReviewRow[] = slice.map((t) => ({
    ticket_id: t.id,
    external_ticket_id: t.externalTicketId,
    subject: t.subject,
    channel: String(t.channel),
    priority: String(t.priority),
    processing_status: String(t.processingStatus),
    assigned_agent: {
      id: t.assignedAgent.id,
      full_name: t.assignedAgent.fullName,
      email: t.assignedAgent.email,
    },
    ticket_closed_at: t.ticketClosedAt.toISOString(),
    ai_qa_summary: t.aiQaReport
      ? {
          agent_score: t.aiQaReport.agentScore,
          resolution_status: String(t.aiQaReport.resolutionStatus),
          is_resolved_properly: t.aiQaReport.isResolvedProperly,
          premature_closure_detected: t.aiQaReport.prematureClosureDetected,
          empathy_rating: t.aiQaReport.empathyRating,
          clarity_and_accuracy_rating: t.aiQaReport.clarityAndAccuracyRating,
          ownership_and_efficiency_rating:
            t.aiQaReport.ownershipAndEfficiencyRating,
          issue_category: String(t.aiQaReport.issueCategory),
          customer_sentiment_trajectory: String(
            t.aiQaReport.customerSentimentTrajectory
          ),
        }
      : null,
    feedback_status: t.managerFeedbacks[0]?.readStatus
      ? String(t.managerFeedbacks[0].readStatus)
      : "NONE",
  }));

  return {
    data,
    pagination: {
      page,
      limit,
      total_records: totalRecords,
      total_pages: totalPages,
    },
  };
}

/**
 * Dual-Mode Detailed Ticket + Transcript + AI Report + Manager Feedback History:
 * Attempts FastAPI (`GET /api/v1/tickets/{ticketId}`) and falls back to Prisma.
 */
export async function fetchTicketDetailById(
  accessToken: string,
  ticketId: string,
  currentUser: { id: string; role: string }
): Promise<TicketDetailResponse | null> {
  const fastApiRes = await tryFetchFastApi<TicketDetailResponse>(
    `/api/v1/tickets/${ticketId}`,
    accessToken
  );
  if (fastApiRes && fastApiRes.ticket_id) {
    return fastApiRes;
  }

  let tkt;
  try {
    tkt = await prisma.ticket.findUnique({
      where: { id: ticketId },
      include: {
        assignedAgent: true,
        aiQaReport: true,
        managerFeedbacks: {
          include: {
            manager: true,
          },
          orderBy: {
            createdAt: "desc",
          },
        },
      },
    });
  } catch {
    return null;
  }

  if (!tkt) {
    return null;
  }

  if (
    currentUser.role === "AGENT" &&
    tkt.assignedAgentId !== currentUser.id
  ) {
    return null;
  }

  const rawTurns = Array.isArray(tkt.rawTranscript)
    ? (tkt.rawTranscript as unknown as TranscriptMessageTurn[])
    : [];

  const rep = tkt.aiQaReport;

  return {
    ticket_id: tkt.id,
    external_ticket_id: tkt.externalTicketId,
    integration_id: tkt.integrationId,
    subject: tkt.subject,
    channel: String(tkt.channel),
    priority: String(tkt.priority),
    processing_status: String(tkt.processingStatus),
    customer_identifier: tkt.customerIdentifier,
    first_response_time_seconds: tkt.firstResponseTimeSeconds,
    total_resolution_time_seconds: tkt.totalResolutionTimeSeconds,
    ticket_created_at: tkt.ticketCreatedAt.toISOString(),
    ticket_closed_at: tkt.ticketClosedAt.toISOString(),
    assigned_agent: {
      id: tkt.assignedAgent.id,
      full_name: tkt.assignedAgent.fullName,
      email: tkt.assignedAgent.email,
    },
    raw_transcript: rawTurns,
    ticket_metadata:
      typeof tkt.ticketMetadata === "object" && tkt.ticketMetadata !== null
        ? (tkt.ticketMetadata as Record<string, unknown>)
        : {},
    ai_qa_report: rep
      ? {
          id: rep.id,
          ticket_id: rep.ticketId,
          summary: rep.summary,
          core_issue: rep.coreIssue,
          issue_category: String(rep.issueCategory),
          resolution_status: String(rep.resolutionStatus),
          is_resolved_properly: rep.isResolvedProperly,
          premature_closure_detected: rep.prematureClosureDetected,
          premature_closure_reason: rep.prematureClosureReason,
          agent_score: rep.agentScore,
          empathy_rating: rep.empathyRating,
          clarity_and_accuracy_rating: rep.clarityAndAccuracyRating,
          ownership_and_efficiency_rating: rep.ownershipAndEfficiencyRating,
          customer_sentiment_trajectory: String(
            rep.customerSentimentTrajectory
          ),
          strengths: Array.isArray(rep.strengths)
            ? (rep.strengths as string[])
            : [],
          areas_for_improvement: Array.isArray(rep.areasForImprovement)
            ? (rep.areasForImprovement as string[])
            : [],
          flagged_evidence_quotes: Array.isArray(rep.flaggedEvidenceQuotes)
            ? (rep.flaggedEvidenceQuotes as unknown as FlaggedEvidenceQuoteItem[])
            : [],
          actionable_coaching_plan: Array.isArray(rep.actionableCoachingPlan)
            ? (rep.actionableCoachingPlan as unknown as CoachingPlanItemData[])
            : [],
          model_used: rep.modelUsed,
          prompt_tokens: rep.promptTokens,
          completion_tokens: rep.completionTokens,
          inference_latency_ms: rep.inferenceLatencyMs,
          evaluated_at: rep.evaluatedAt.toISOString(),
        }
      : null,
    manager_feedbacks: tkt.managerFeedbacks.map((fb) => ({
      id: fb.id,
      ticket_id: fb.ticketId,
      manager_id: fb.managerId,
      manager: fb.manager
        ? {
            id: fb.manager.id,
            full_name: fb.manager.fullName,
            email: fb.manager.email,
          }
        : null,
      agent_id: fb.agentId,
      manager_override_score: fb.managerOverrideScore,
      coaching_priority: String(fb.coachingPriority),
      comments: fb.comments,
      action_items: Array.isArray(fb.actionItems)
        ? (fb.actionItems as unknown as FeedbackActionItem[])
        : [],
      read_status: String(fb.readStatus),
      agent_acknowledgement_note: fb.agentAcknowledgementNote,
      read_at: fb.readAt ? fb.readAt.toISOString() : null,
      acknowledged_at: fb.acknowledgedAt
        ? fb.acknowledgedAt.toISOString()
        : null,
      created_at: fb.createdAt.toISOString(),
      updated_at: fb.updatedAt.toISOString(),
    })),
  };
}

/**
 * Dual-Mode Agent Personal Summary & Coaching History (`GET /api/v1/agent/me/summary`):
 * Strictly isolated to `agentId`.
 */
export async function fetchAgentPersonalSummary(
  accessToken: string,
  user: { id: string; email: string; fullName: string }
): Promise<AgentPersonalSummaryData> {
  const fastApiRes = await tryFetchFastApi<AgentPersonalSummaryData>(
    "/api/v1/agent/me/summary",
    accessToken
  );
  if (fastApiRes && fastApiRes.kpis) {
    return fastApiRes;
  }

  const [tickets, feedbacks] = await Promise.all([
    prisma.ticket.findMany({
      where: {
        assignedAgentId: user.id,
        aiQaReport: {
          isNot: null,
        },
      },
      include: {
        aiQaReport: true,
      },
      orderBy: {
        ticketClosedAt: "desc",
      },
    }),
    prisma.managerFeedback.findMany({
      where: {
        agentId: user.id,
      },
    }),
  ]);

  const unreadCount = feedbacks.filter(
    (fb) => String(fb.readStatus) === "UNREAD"
  ).length;
  const highPriorityUnreadCount = feedbacks.filter(
    (fb) =>
      String(fb.readStatus) === "UNREAD" &&
      ["HIGH", "CRITICAL"].includes(String(fb.coachingPriority))
  ).length;

  const totalEvaluated = tickets.length;
  if (totalEvaluated === 0) {
    return {
      agent: {
        id: user.id,
        email: user.email,
        full_name: user.fullName,
      },
      kpis: {
        total_tickets_evaluated: 0,
        average_agent_score: 0,
        proper_resolution_rate_pct: 0,
        premature_closure_rate_pct: 0,
        avg_empathy_rating: 0,
        avg_clarity_rating: 0,
        avg_ownership_rating: 0,
        unread_feedback_count: unreadCount,
        high_priority_unread_count: highPriorityUnreadCount,
      },
      score_trend_daily: [],
      recent_coaching_plans: [],
    };
  }

  let scoreSum = 0;
  let properCount = 0;
  let prematureCount = 0;
  let empathySum = 0;
  let claritySum = 0;
  let ownershipSum = 0;

  const dailyMap = new Map<string, { scoreSum: number; count: number }>();
  const recentCoaching: AgentPersonalSummaryData["recent_coaching_plans"] = [];

  for (const tkt of tickets) {
    const rep = tkt.aiQaReport;
    if (!rep) continue;

    scoreSum += rep.agentScore;
    empathySum += rep.empathyRating;
    claritySum += rep.clarityAndAccuracyRating;
    ownershipSum += rep.ownershipAndEfficiencyRating;
    if (rep.isResolvedProperly) properCount += 1;
    if (rep.prematureClosureDetected) prematureCount += 1;

    const dayKey = tkt.ticketClosedAt.toISOString().slice(0, 10);
    const b = dailyMap.get(dayKey) || { scoreSum: 0, count: 0 };
    b.scoreSum += rep.agentScore;
    b.count += 1;
    dailyMap.set(dayKey, b);

    if (recentCoaching.length < 15) {
      recentCoaching.push({
        ticket_id: tkt.id,
        external_ticket_id: tkt.externalTicketId,
        subject: tkt.subject,
        ticket_closed_at: tkt.ticketClosedAt.toISOString(),
        agent_score: rep.agentScore,
        resolution_status: String(rep.resolutionStatus),
        issue_category: String(rep.issueCategory),
        strengths: Array.isArray(rep.strengths)
          ? (rep.strengths as string[])
          : [],
        areas_for_improvement: Array.isArray(rep.areasForImprovement)
          ? (rep.areasForImprovement as string[])
          : [],
        actionable_coaching_plan: Array.isArray(rep.actionableCoachingPlan)
          ? (rep.actionableCoachingPlan as unknown as CoachingPlanItemData[])
          : [],
      });
    }
  }

  const score_trend_daily = Array.from(dailyMap.entries())
    .map(([date, b]) => ({
      date,
      avg_score: Number((b.scoreSum / b.count).toFixed(1)),
      total_tickets: b.count,
    }))
    .sort((a, b) => a.date.localeCompare(b.date));

  return {
    agent: {
      id: user.id,
      email: user.email,
      full_name: user.fullName,
    },
    kpis: {
      total_tickets_evaluated: totalEvaluated,
      average_agent_score: Number((scoreSum / totalEvaluated).toFixed(1)),
      proper_resolution_rate_pct: Number(
        ((properCount / totalEvaluated) * 100).toFixed(1)
      ),
      premature_closure_rate_pct: Number(
        ((prematureCount / totalEvaluated) * 100).toFixed(1)
      ),
      avg_empathy_rating: Number((empathySum / totalEvaluated).toFixed(1)),
      avg_clarity_rating: Number((claritySum / totalEvaluated).toFixed(1)),
      avg_ownership_rating: Number((ownershipSum / totalEvaluated).toFixed(1)),
      unread_feedback_count: unreadCount,
      high_priority_unread_count: highPriorityUnreadCount,
    },
    score_trend_daily,
    recent_coaching_plans: recentCoaching,
  };
}

/**
 * Dual-Mode Agent Feedback Inbox (`GET /api/v1/agent/me/feedback`):
 * Strictly isolated to `agentId`.
 */
export async function fetchAgentFeedbackInbox(
  accessToken: string,
  agentId: string
): Promise<ManagerFeedbackItemData[]> {
  const fastApiRes = await tryFetchFastApi<{
    data: ManagerFeedbackItemData[];
  }>("/api/v1/agent/me/feedback?limit=50", accessToken);
  if (fastApiRes && Array.isArray(fastApiRes.data)) {
    return fastApiRes.data;
  }

  const feedbacks = await prisma.managerFeedback.findMany({
    where: {
      agentId,
    },
    include: {
      manager: true,
      ticket: {
        include: {
          aiQaReport: true,
        },
      },
    },
    orderBy: {
      createdAt: "desc",
    },
  });

  return feedbacks.map((fb) => ({
    id: fb.id,
    ticket_id: fb.ticketId,
    manager_id: fb.managerId,
    manager: fb.manager
      ? {
          id: fb.manager.id,
          full_name: fb.manager.fullName,
          email: fb.manager.email,
        }
      : null,
    agent_id: fb.agentId,
    manager_override_score: fb.managerOverrideScore,
    coaching_priority: String(fb.coachingPriority),
    comments: fb.comments,
    action_items: Array.isArray(fb.actionItems)
      ? (fb.actionItems as unknown as FeedbackActionItem[])
      : [],
    read_status: String(fb.readStatus),
    agent_acknowledgement_note: fb.agentAcknowledgementNote,
    read_at: fb.readAt ? fb.readAt.toISOString() : null,
    acknowledged_at: fb.acknowledgedAt
      ? fb.acknowledgedAt.toISOString()
      : null,
    created_at: fb.createdAt.toISOString(),
    updated_at: fb.updatedAt.toISOString(),
    ticket: fb.ticket
      ? {
          ticket_id: fb.ticket.id,
          external_ticket_id: fb.ticket.externalTicketId,
          subject: fb.ticket.subject,
          ticket_closed_at: fb.ticket.ticketClosedAt.toISOString(),
          ai_agent_score: fb.ticket.aiQaReport?.agentScore ?? null,
          resolution_status: fb.ticket.aiQaReport
            ? String(fb.ticket.aiQaReport.resolutionStatus)
            : null,
        }
      : null,
  }));
}

