import {
  PrismaClient,
  UserRole,
  CrmType,
  TicketChannel,
  TicketPriority,
  ProcessingStatus,
  IssueCategory,
  ResolutionStatus,
  SentimentTrajectory,
  CoachingPriority,
  FeedbackReadStatus,
} from "@prisma/client";
import bcrypt from "bcryptjs";

const prisma = new PrismaClient();

export const SEED_IDS = {
  ADMIN_USER_ID: "11111111-1111-4111-8111-111111111101",
  MANAGER_USER_ID: "11111111-1111-4111-8111-111111111102",
  SARAH_AGENT_ID: "11111111-1111-4111-8111-111111111103",
  OMAR_AGENT_ID: "11111111-1111-4111-8111-111111111104",
  ZENDESK_INTEGRATION_ID: "22222222-2222-4222-8222-222222222201",
  SAMPLE_TICKET_ID: "33333333-3333-4333-8333-333333333301",
  SAMPLE_QA_REPORT_ID: "44444444-4444-4444-8444-444444444401",
  SAMPLE_FEEDBACK_ID: "55555555-5555-4555-8555-555555555501",
} as const;

export const DEFAULT_SEED_PASSWORD = "Password123!";

async function main(): Promise<void> {
  console.log("🌱 Starting deterministic Phase 1 database seed...");

  const passwordHash = await bcrypt.hash(DEFAULT_SEED_PASSWORD, 12);

  // 1. Admin User
  const adminUser = await prisma.user.upsert({
    where: { email: "admin@qa-platform.local" },
    update: {
      passwordHash,
      fullName: "Elena Vance",
      role: UserRole.ADMIN,
      isActive: true,
    },
    create: {
      id: SEED_IDS.ADMIN_USER_ID,
      email: "admin@qa-platform.local",
      passwordHash,
      fullName: "Elena Vance",
      role: UserRole.ADMIN,
      isActive: true,
    },
  });

  // 2. Manager User
  const managerUser = await prisma.user.upsert({
    where: { email: "manager@qa-platform.local" },
    update: {
      passwordHash,
      fullName: "Marcus Sterling",
      role: UserRole.MANAGER,
      isActive: true,
    },
    create: {
      id: SEED_IDS.MANAGER_USER_ID,
      email: "manager@qa-platform.local",
      passwordHash,
      fullName: "Marcus Sterling",
      role: UserRole.MANAGER,
      isActive: true,
    },
  });

  // 3. Agent User 1: Sarah Jenkins (zd_agent_101)
  const sarahAgent = await prisma.user.upsert({
    where: { email: "sarah.agent@qa-platform.local" },
    update: {
      passwordHash,
      fullName: "Sarah Jenkins",
      role: UserRole.AGENT,
      externalCrmAgentId: "zd_agent_101",
      managerId: managerUser.id,
      isActive: true,
    },
    create: {
      id: SEED_IDS.SARAH_AGENT_ID,
      email: "sarah.agent@qa-platform.local",
      passwordHash,
      fullName: "Sarah Jenkins",
      role: UserRole.AGENT,
      externalCrmAgentId: "zd_agent_101",
      managerId: managerUser.id,
      isActive: true,
    },
  });

  // 4. Agent User 2: Omar Hassan (zd_agent_102)
  const omarAgent = await prisma.user.upsert({
    where: { email: "omar.agent@qa-platform.local" },
    update: {
      passwordHash,
      fullName: "Omar Hassan",
      role: UserRole.AGENT,
      externalCrmAgentId: "zd_agent_102",
      managerId: managerUser.id,
      isActive: true,
    },
    create: {
      id: SEED_IDS.OMAR_AGENT_ID,
      email: "omar.agent@qa-platform.local",
      passwordHash,
      fullName: "Omar Hassan",
      role: UserRole.AGENT,
      externalCrmAgentId: "zd_agent_102",
      managerId: managerUser.id,
      isActive: true,
    },
  });

  // 5. Active Zendesk Integration
  const zendeskIntegration = await prisma.integration.upsert({
    where: { id: SEED_IDS.ZENDESK_INTEGRATION_ID },
    update: {
      name: "Acme Support Zendesk Production",
      crmType: CrmType.ZENDESK,
      subdomainOrBaseUrl: "https://acme-support.zendesk.com",
      encryptedApiKey: "enc_aes256gcm_v1:dummy_zendesk_api_key_ciphertext_9f8a7b6c",
      encryptedWebhookSecret: "enc_aes256gcm_v1:dummy_zendesk_webhook_secret_ciphertext_1a2b3c4d",
      configMetadata: {
        environment: "production",
        syncIntervalMinutes: 15,
        closedStatuses: ["closed", "solved"],
      },
      isActive: true,
      lastSuccessfulSyncAt: new Date("2026-10-28T15:00:00.000Z"),
    },
    create: {
      id: SEED_IDS.ZENDESK_INTEGRATION_ID,
      name: "Acme Support Zendesk Production",
      crmType: CrmType.ZENDESK,
      subdomainOrBaseUrl: "https://acme-support.zendesk.com",
      encryptedApiKey: "enc_aes256gcm_v1:dummy_zendesk_api_key_ciphertext_9f8a7b6c",
      encryptedWebhookSecret: "enc_aes256gcm_v1:dummy_zendesk_webhook_secret_ciphertext_1a2b3c4d",
      configMetadata: {
        environment: "production",
        syncIntervalMinutes: 15,
        closedStatuses: ["closed", "solved"],
      },
      isActive: true,
      lastSuccessfulSyncAt: new Date("2026-10-28T15:00:00.000Z"),
    },
  });

  // 6. Sample Evaluated Ticket (Linked to Sarah Jenkins)
  const ticketCreatedAt = new Date("2026-10-28T13:10:00.000Z");
  const ticketClosedAt = new Date("2026-10-28T14:22:10.000Z");

  const sampleTranscript = [
    {
      message_id: "msg_1001",
      sender_role: "CUSTOMER",
      sender_name: "Customer #4821",
      timestamp: "2026-10-28T13:10:00Z",
      content:
        "Our production webhook endpoint started returning 403 Forbidden immediately after we rotated our API signing key in the dashboard. We already tried regenerating the secret twice and restarting our workers, but signatures still fail.",
      is_internal_note: false,
    },
    {
      message_id: "msg_1002",
      sender_role: "AGENT",
      sender_name: "Sarah Jenkins",
      timestamp: "2026-10-28T13:14:20Z",
      content:
        "Hi there! You can fix API key issues by reading our key rotation guide here: https://docs.acme.local/webhooks/key-rotation. I am marking this ticket as solved now.",
      is_internal_note: false,
    },
    {
      message_id: "msg_1003",
      sender_role: "CUSTOMER",
      sender_name: "Customer #4821",
      timestamp: "2026-10-28T13:18:05Z",
      content:
        "Wait, please don't close this! As I mentioned, we already followed that exact guide and regenerated the secret twice. Does the V2 endpoint require Base64 or Hex encoding for the HMAC digest?",
      is_internal_note: false,
    },
  ];

  const sampleTicket = await prisma.ticket.upsert({
    where: { id: SEED_IDS.SAMPLE_TICKET_ID },
    update: {
      integrationId: zendeskIntegration.id,
      externalTicketId: "ZD-99412",
      assignedAgentId: sarahAgent.id,
      customerIdentifier: "cust_hash_88f91a2c",
      subject: "API webhook failing with 403 error after key rotation",
      channel: TicketChannel.EMAIL,
      priority: TicketPriority.HIGH,
      processingStatus: ProcessingStatus.EVALUATED,
      rawTranscript: sampleTranscript,
      ticketMetadata: {
        tags: ["api", "webhooks", "auth-403", "enterprise"],
        via: "email",
      },
      firstResponseTimeSeconds: 260,
      totalResolutionTimeSeconds: 4330,
      ticketCreatedAt,
      ticketClosedAt,
    },
    create: {
      id: SEED_IDS.SAMPLE_TICKET_ID,
      integrationId: zendeskIntegration.id,
      externalTicketId: "ZD-99412",
      assignedAgentId: sarahAgent.id,
      customerIdentifier: "cust_hash_88f91a2c",
      subject: "API webhook failing with 403 error after key rotation",
      channel: TicketChannel.EMAIL,
      priority: TicketPriority.HIGH,
      processingStatus: ProcessingStatus.EVALUATED,
      rawTranscript: sampleTranscript,
      ticketMetadata: {
        tags: ["api", "webhooks", "auth-403", "enterprise"],
        via: "email",
      },
      firstResponseTimeSeconds: 260,
      totalResolutionTimeSeconds: 4330,
      ticketCreatedAt,
      ticketClosedAt,
    },
  });

  // 7. Sample AI QA Report (Linked 1:1 to Sample Ticket)
  const sampleReport = await prisma.aiQaReport.upsert({
    where: { ticketId: sampleTicket.id },
    update: {
      summary:
        "The customer reported persistent 403 errors on their production webhook after rotating their signing secret despite regenerating keys twice. The agent replied with a generic documentation link and immediately closed the ticket, leaving the customer's follow-up question about Base64 vs. Hex HMAC encoding unanswered.",
      coreIssue:
        "Webhook HMAC signature verification failing with HTTP 403 after API signing key rotation.",
      issueCategory: IssueCategory.TECHNICAL_BUG,
      resolutionStatus: ResolutionStatus.PREMATURELY_CLOSED,
      isResolvedProperly: false,
      prematureClosureDetected: true,
      prematureClosureReason:
        "Agent performed a drive-by documentation link drop and closed the ticket while the customer had an active production blocker and an unanswered technical question regarding Base64 vs. Hex HMAC digest encoding.",
      agentScore: 42,
      empathyRating: 6,
      clarityAndAccuracyRating: 5,
      ownershipAndEfficiencyRating: 3,
      customerSentimentTrajectory: SentimentTrajectory.DEGRADED,
      strengths: [
        "Fast initial response time (under 5 minutes from ticket creation).",
      ],
      areasForImprovement: [
        "Closed the ticket immediately after dropping a generic documentation link without verifying the fix.",
        "Ignored the customer's statement that they had already tried regenerating the secret twice.",
        "Left the customer's explicit question about Base64 vs. Hex HMAC encoding unanswered.",
      ],
      flaggedEvidenceQuotes: [
        {
          speaker: "AGENT",
          quote:
            "You can fix API key issues by reading our key rotation guide here: https://docs.acme.local/webhooks/key-rotation. I am marking this ticket as solved now.",
          issue_type: "PREMATURE_CLOSURE",
        },
        {
          speaker: "CUSTOMER",
          quote:
            "Wait, please don't close this! As I mentioned, we already followed that exact guide and regenerated the secret twice. Does the V2 endpoint require Base64 or Hex encoding for the HMAC digest?",
          issue_type: "IGNORED_QUESTION",
        },
      ],
      actionableCoachingPlan: [
        {
          focus_area: "Confirming Resolution Before Closure",
          specific_action:
            "Acknowledge the troubleshooting steps the customer already completed and directly answer their encoding question before proposing closure.",
          suggested_phrasing_example:
            "I see you've already regenerated the signing secret twice and restarted your workers. For V2 webhooks, the HMAC-SHA256 digest must be Base64-encoded rather than Hex-encoded. Could you verify if your worker is encoding the signature in Base64 and let me know if the 403 persists?",
        },
      ],
      modelUsed: "llama-3.3-70b-versatile",
      promptTokens: 1120,
      completionTokens: 485,
      inferenceLatencyMs: 640,
      evaluatedAt: new Date("2026-10-28T14:22:18.000Z"),
    },
    create: {
      id: SEED_IDS.SAMPLE_QA_REPORT_ID,
      ticketId: sampleTicket.id,
      summary:
        "The customer reported persistent 403 errors on their production webhook after rotating their signing secret despite regenerating keys twice. The agent replied with a generic documentation link and immediately closed the ticket, leaving the customer's follow-up question about Base64 vs. Hex HMAC encoding unanswered.",
      coreIssue:
        "Webhook HMAC signature verification failing with HTTP 403 after API signing key rotation.",
      issueCategory: IssueCategory.TECHNICAL_BUG,
      resolutionStatus: ResolutionStatus.PREMATURELY_CLOSED,
      isResolvedProperly: false,
      prematureClosureDetected: true,
      prematureClosureReason:
        "Agent performed a drive-by documentation link drop and closed the ticket while the customer had an active production blocker and an unanswered technical question regarding Base64 vs. Hex HMAC digest encoding.",
      agentScore: 42,
      empathyRating: 6,
      clarityAndAccuracyRating: 5,
      ownershipAndEfficiencyRating: 3,
      customerSentimentTrajectory: SentimentTrajectory.DEGRADED,
      strengths: [
        "Fast initial response time (under 5 minutes from ticket creation).",
      ],
      areasForImprovement: [
        "Closed the ticket immediately after dropping a generic documentation link without verifying the fix.",
        "Ignored the customer's statement that they had already tried regenerating the secret twice.",
        "Left the customer's explicit question about Base64 vs. Hex HMAC encoding unanswered.",
      ],
      flaggedEvidenceQuotes: [
        {
          speaker: "AGENT",
          quote:
            "You can fix API key issues by reading our key rotation guide here: https://docs.acme.local/webhooks/key-rotation. I am marking this ticket as solved now.",
          issue_type: "PREMATURE_CLOSURE",
        },
        {
          speaker: "CUSTOMER",
          quote:
            "Wait, please don't close this! As I mentioned, we already followed that exact guide and regenerated the secret twice. Does the V2 endpoint require Base64 or Hex encoding for the HMAC digest?",
          issue_type: "IGNORED_QUESTION",
        },
      ],
      actionableCoachingPlan: [
        {
          focus_area: "Confirming Resolution Before Closure",
          specific_action:
            "Acknowledge the troubleshooting steps the customer already completed and directly answer their encoding question before proposing closure.",
          suggested_phrasing_example:
            "I see you've already regenerated the signing secret twice and restarted your workers. For V2 webhooks, the HMAC-SHA256 digest must be Base64-encoded rather than Hex-encoded. Could you verify if your worker is encoding the signature in Base64 and let me know if the 403 persists?",
        },
      ],
      modelUsed: "llama-3.3-70b-versatile",
      promptTokens: 1120,
      completionTokens: 485,
      inferenceLatencyMs: 640,
      evaluatedAt: new Date("2026-10-28T14:22:18.000Z"),
    },
  });

  // 8. Sample Unread Manager Feedback (Authored by Marcus Sterling, Assigned to Sarah Jenkins)
  const sampleFeedback = await prisma.managerFeedback.upsert({
    where: { id: SEED_IDS.SAMPLE_FEEDBACK_ID },
    update: {
      ticketId: sampleTicket.id,
      managerId: managerUser.id,
      agentId: sarahAgent.id,
      managerOverrideScore: 40,
      coachingPriority: CoachingPriority.HIGH,
      comments:
        "Sarah, you sent the documentation link for API key rotation and immediately closed the ticket while the customer explicitly stated they already tried regenerating the secret. Never close a technical blocker without confirming the customer's test succeeded.",
      actionItems: [
        {
          id: "act_1",
          description:
            "Re-open ticket ZD-99412 and ask the customer for the failing request ID header.",
          completed: false,
        },
        {
          id: "act_2",
          description:
            "Review the 'Webhook Troubleshooting Playbook' section on HMAC header encoding.",
          completed: false,
        },
      ],
      readStatus: FeedbackReadStatus.UNREAD,
      agentAcknowledgementNote: null,
      readAt: null,
      acknowledgedAt: null,
    },
    create: {
      id: SEED_IDS.SAMPLE_FEEDBACK_ID,
      ticketId: sampleTicket.id,
      managerId: managerUser.id,
      agentId: sarahAgent.id,
      managerOverrideScore: 40,
      coachingPriority: CoachingPriority.HIGH,
      comments:
        "Sarah, you sent the documentation link for API key rotation and immediately closed the ticket while the customer explicitly stated they already tried regenerating the secret. Never close a technical blocker without confirming the customer's test succeeded.",
      actionItems: [
        {
          id: "act_1",
          description:
            "Re-open ticket ZD-99412 and ask the customer for the failing request ID header.",
          completed: false,
        },
        {
          id: "act_2",
          description:
            "Review the 'Webhook Troubleshooting Playbook' section on HMAC header encoding.",
          completed: false,
        },
      ],
      readStatus: FeedbackReadStatus.UNREAD,
      agentAcknowledgementNote: null,
      readAt: null,
      acknowledgedAt: null,
    },
  });

  console.log("✅ Seed completed successfully:");
  console.log(`   • Admin:       ${adminUser.email} (${adminUser.id})`);
  console.log(`   • Manager:     ${managerUser.email} (${managerUser.id})`);
  console.log(`   • Agent 1:     ${sarahAgent.email} (${sarahAgent.id}) [CRM: ${sarahAgent.externalCrmAgentId}]`);
  console.log(`   • Agent 2:     ${omarAgent.email} (${omarAgent.id}) [CRM: ${omarAgent.externalCrmAgentId}]`);
  console.log(`   • Integration: ${zendeskIntegration.name} (${zendeskIntegration.id})`);
  console.log(`   • Ticket:      ${sampleTicket.externalTicketId} (${sampleTicket.id})`);
  console.log(`   • AI Report:   Score=${sampleReport.agentScore}, Status=${sampleReport.resolutionStatus}`);
  console.log(`   • Feedback:    Priority=${sampleFeedback.coachingPriority}, ReadStatus=${sampleFeedback.readStatus}`);
}

main()
  .catch((error) => {
    console.error("❌ Seed failed:", error);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });

