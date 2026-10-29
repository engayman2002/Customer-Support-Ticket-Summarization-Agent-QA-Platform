import { describe, expect, it } from "vitest";
import {
  type FeedbackActionItem,
  type FlaggedEvidenceQuoteItem,
  applyTicketFilterPreset,
  buildFeedbackStatusPatchPayload,
  buildTicketFilterQueryString,
  canAcknowledgeFeedback,
  formatSentimentTrajectory,
  getIssueTypeHighlightStyle,
  getResolutionBadgeClasses,
  getScoreBadgeClasses,
  getScoreBadgeVariant,
  highlightTranscriptText,
} from "@/lib/dashboard-utils";

describe("Phase 4B: Manager & Agent Dashboards Domain Logic Suite", () => {
  describe("1. Transcript Inline Evidence Quote Highlighter", () => {
    it("accurately splits and highlights verbatim quotes without corrupting surrounding text", () => {
      const messageText =
        "Hello! Please check our FAQ at https://help.acme.local/sso. Closing this ticket now. Have a nice day.";
      const flaggedQuotes: FlaggedEvidenceQuoteItem[] = [
        {
          speaker: "AGENT",
          quote: "Closing this ticket now.",
          issue_type: "PREMATURE_CLOSURE",
        },
      ];

      const segments = highlightTranscriptText(messageText, flaggedQuotes);
      expect(segments).toHaveLength(3);
      expect(segments[0]).toEqual({
        text: "Hello! Please check our FAQ at https://help.acme.local/sso. ",
      });
      expect(segments[1]).toEqual({
        text: "Closing this ticket now.",
        matchedQuote: flaggedQuotes[0],
      });
      expect(segments[2]).toEqual({
        text: " Have a nice day.",
      });

      // Re-concatenating segments must equal the exact original transcript turn
      const reconstructed = segments.map((s) => s.text).join("");
      expect(reconstructed).toBe(messageText);
    });

    it("supports multiple distinct flagged quotes in a single message and maps severity colors", () => {
      const turnText =
        "If you had read the manual you would know this. Also I am closing this ticket without checking your second question.";
      const quotes: FlaggedEvidenceQuoteItem[] = [
        {
          speaker: "AGENT",
          quote: "If you had read the manual",
          issue_type: "POOR_TONE",
        },
        {
          speaker: "AGENT",
          quote: "without checking your second question",
          issue_type: "IGNORED_QUESTION",
        },
      ];

      const segments = highlightTranscriptText(turnText, quotes);
      const matched = segments.filter((s) => Boolean(s.matchedQuote));
      expect(matched).toHaveLength(2);
      expect(matched[0].matchedQuote?.issue_type).toBe("POOR_TONE");
      expect(matched[1].matchedQuote?.issue_type).toBe("IGNORED_QUESTION");

      expect(getIssueTypeHighlightStyle("PREMATURE_CLOSURE").severity).toBe(
        "rose"
      );
      expect(getIssueTypeHighlightStyle("POOR_TONE").severity).toBe("rose");
      expect(getIssueTypeHighlightStyle("IGNORED_QUESTION").severity).toBe(
        "amber"
      );
      expect(getIssueTypeHighlightStyle("UNHELPFUL_RESPONSE").severity).toBe(
        "amber"
      );
    });
  });

  describe("2. Ticket Review Filter Presets & URL Query String Builder", () => {
    it("serializes Quick Filter Presets (Premature Closures, Low Score < 60, Pending Feedback)", () => {
      const prematureParams = applyTicketFilterPreset("PREMATURE_CLOSURES", {
        limit: 25,
        agentId: "agent_101",
      });
      expect(prematureParams.resolutionStatus).toBe("PREMATURELY_CLOSED");
      expect(prematureParams.prematureClosureOnly).toBe(true);
      const prematureQs = buildTicketFilterQueryString(prematureParams);
      expect(prematureQs).toContain("resolutionStatus=PREMATURELY_CLOSED");
      expect(prematureQs).toContain("prematureClosureOnly=true");
      expect(prematureQs).toContain("agentId=agent_101");

      const lowScoreParams = applyTicketFilterPreset("LOW_SCORE");
      expect(lowScoreParams.maxScore).toBe(59);
      expect(buildTicketFilterQueryString(lowScoreParams)).toContain(
        "maxScore=59"
      );

      const pendingParams = applyTicketFilterPreset("PENDING_FEEDBACK");
      expect(pendingParams.pendingFeedbackOnly).toBe(true);
      expect(buildTicketFilterQueryString(pendingParams)).toContain(
        "pendingFeedbackOnly=true"
      );

      const allParams = applyTicketFilterPreset("ALL", { search: "ZD-99412" });
      expect(allParams.resolutionStatus).toBeUndefined();
      expect(allParams.maxScore).toBeUndefined();
      expect(buildTicketFilterQueryString(allParams)).toContain(
        "search=ZD-99412"
      );
    });
  });

  describe("3. Agent Inbox Action-Item Completion Gate & PATCH Payload Builder", () => {
    const twoActionItems: FeedbackActionItem[] = [
      {
        id: "act_1",
        description: "Re-open ticket ZD-99412 and request failing request ID.",
        completed: false,
      },
      {
        id: "act_2",
        description: "Review the Webhook Troubleshooting Playbook.",
        completed: false,
      },
    ];

    it("disables acknowledgement when 0 or 1 action items are checked and enables only when all are checked", () => {
      // 0 items checked -> false
      expect(canAcknowledgeFeedback(twoActionItems, new Set())).toBe(false);

      // 1 of 2 items checked -> false
      expect(canAcknowledgeFeedback(twoActionItems, new Set(["act_1"]))).toBe(
        false
      );

      // All 2 items checked -> true
      expect(
        canAcknowledgeFeedback(twoActionItems, new Set(["act_1", "act_2"]))
      ).toBe(true);
    });

    it("builds the exact Section 5.2 PATCH /api/v1/feedback/{id}/status payload", () => {
      const payload = buildFeedbackStatusPatchPayload({
        readStatus: "ACKNOWLEDGED",
        completedActionItemIds: ["act_1", "act_2"],
        agentAcknowledgementNote:
          "  Understood. Reopened ZD-99412 and resolved HMAC mismatch.  ",
      });

      expect(payload).toEqual({
        read_status: "ACKNOWLEDGED",
        completed_action_item_ids: ["act_1", "act_2"],
        agent_acknowledgement_note:
          "Understood. Reopened ZD-99412 and resolved HMAC mismatch.",
      });
    });
  });

  describe("4. Score & Rubric Badge Color Thresholds", () => {
    it("maps >= 80 to emerald, 60-79 to amber, and < 60 to rose", () => {
      expect(getScoreBadgeVariant(94)).toBe("emerald");
      expect(getScoreBadgeVariant(80)).toBe("emerald");
      expect(getScoreBadgeClasses(85)).toContain("emerald");

      expect(getScoreBadgeVariant(79)).toBe("amber");
      expect(getScoreBadgeVariant(60)).toBe("amber");
      expect(getScoreBadgeClasses(68)).toContain("amber");

      expect(getScoreBadgeVariant(59)).toBe("rose");
      expect(getScoreBadgeVariant(35)).toBe("rose");
      expect(getScoreBadgeClasses(42)).toContain("rose");

      expect(getResolutionBadgeClasses("RESOLVED")).toContain("emerald");
      expect(getResolutionBadgeClasses("PREMATURELY_CLOSED")).toContain("rose");
      expect(formatSentimentTrajectory("IMPROVED").label).toContain("Improved");
      expect(formatSentimentTrajectory("DEGRADED").label).toContain("Degraded");
    });
  });
});

