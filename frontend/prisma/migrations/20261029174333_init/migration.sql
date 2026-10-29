-- CreateEnum
CREATE TYPE "UserRole" AS ENUM ('ADMIN', 'MANAGER', 'AGENT');

-- CreateEnum
CREATE TYPE "CrmType" AS ENUM ('ZENDESK', 'FRESHDESK', 'INTERCOM', 'CUSTOM');

-- CreateEnum
CREATE TYPE "TicketChannel" AS ENUM ('EMAIL', 'LIVE_CHAT', 'SOCIAL', 'WEB_FORM', 'API');

-- CreateEnum
CREATE TYPE "TicketPriority" AS ENUM ('LOW', 'NORMAL', 'HIGH', 'URGENT');

-- CreateEnum
CREATE TYPE "ProcessingStatus" AS ENUM ('QUEUED', 'PROCESSING', 'EVALUATED', 'FAILED_RETRYABLE', 'FAILED_PERMANENT');

-- CreateEnum
CREATE TYPE "IssueCategory" AS ENUM ('BILLING', 'TECHNICAL_BUG', 'ACCOUNT_ACCESS', 'FEATURE_REQUEST', 'HOW_TO', 'CANCELLATION', 'OTHER');

-- CreateEnum
CREATE TYPE "ResolutionStatus" AS ENUM ('RESOLVED', 'UNRESOLVED', 'PARTIALLY_RESOLVED', 'PREMATURELY_CLOSED', 'ESCALATED_PROPERLY');

-- CreateEnum
CREATE TYPE "SentimentTrajectory" AS ENUM ('IMPROVED', 'UNCHANGED_POSITIVE', 'UNCHANGED_NEGATIVE', 'DEGRADED');

-- CreateEnum
CREATE TYPE "FeedbackReadStatus" AS ENUM ('UNREAD', 'READ', 'ACKNOWLEDGED');

-- CreateEnum
CREATE TYPE "CoachingPriority" AS ENUM ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL');

-- CreateTable
CREATE TABLE "users" (
    "id" UUID NOT NULL,
    "email" VARCHAR(255) NOT NULL,
    "password_hash" TEXT NOT NULL,
    "full_name" VARCHAR(150) NOT NULL,
    "role" "UserRole" NOT NULL DEFAULT 'AGENT',
    "external_crm_agent_id" VARCHAR(128),
    "manager_id" UUID,
    "is_active" BOOLEAN NOT NULL DEFAULT true,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "users_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "integrations" (
    "id" UUID NOT NULL,
    "name" VARCHAR(120) NOT NULL,
    "crm_type" "CrmType" NOT NULL,
    "subdomain_or_base_url" VARCHAR(255) NOT NULL,
    "encrypted_api_key" TEXT NOT NULL,
    "encrypted_webhook_secret" TEXT NOT NULL,
    "config_metadata" JSONB NOT NULL DEFAULT '{}',
    "is_active" BOOLEAN NOT NULL DEFAULT true,
    "last_successful_sync_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "integrations_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "tickets" (
    "id" UUID NOT NULL,
    "integration_id" UUID NOT NULL,
    "external_ticket_id" VARCHAR(128) NOT NULL,
    "assigned_agent_id" UUID NOT NULL,
    "customer_identifier" VARCHAR(255) NOT NULL,
    "subject" VARCHAR(500) NOT NULL,
    "channel" "TicketChannel" NOT NULL DEFAULT 'EMAIL',
    "priority" "TicketPriority" NOT NULL DEFAULT 'NORMAL',
    "processing_status" "ProcessingStatus" NOT NULL DEFAULT 'QUEUED',
    "raw_transcript" JSONB NOT NULL,
    "ticket_metadata" JSONB NOT NULL DEFAULT '{}',
    "first_response_time_seconds" INTEGER,
    "total_resolution_time_seconds" INTEGER,
    "ticket_created_at" TIMESTAMP(3) NOT NULL,
    "ticket_closed_at" TIMESTAMP(3) NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "tickets_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ai_qa_reports" (
    "id" UUID NOT NULL,
    "ticket_id" UUID NOT NULL,
    "summary" TEXT NOT NULL,
    "core_issue" TEXT NOT NULL,
    "issue_category" "IssueCategory" NOT NULL,
    "resolution_status" "ResolutionStatus" NOT NULL,
    "is_resolved_properly" BOOLEAN NOT NULL,
    "premature_closure_detected" BOOLEAN NOT NULL,
    "premature_closure_reason" TEXT,
    "agent_score" SMALLINT NOT NULL,
    "empathy_rating" SMALLINT NOT NULL,
    "clarity_and_accuracy_rating" SMALLINT NOT NULL,
    "ownership_and_efficiency_rating" SMALLINT NOT NULL,
    "customer_sentiment_trajectory" "SentimentTrajectory" NOT NULL,
    "strengths" JSONB NOT NULL,
    "areas_for_improvement" JSONB NOT NULL,
    "flagged_evidence_quotes" JSONB NOT NULL,
    "actionable_coaching_plan" JSONB NOT NULL,
    "model_used" VARCHAR(100) NOT NULL,
    "prompt_tokens" INTEGER NOT NULL,
    "completion_tokens" INTEGER NOT NULL,
    "inference_latency_ms" INTEGER NOT NULL,
    "evaluated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ai_qa_reports_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "manager_feedback" (
    "id" UUID NOT NULL,
    "ticket_id" UUID NOT NULL,
    "manager_id" UUID NOT NULL,
    "agent_id" UUID NOT NULL,
    "manager_override_score" SMALLINT,
    "coaching_priority" "CoachingPriority" NOT NULL DEFAULT 'MEDIUM',
    "comments" TEXT NOT NULL,
    "action_items" JSONB NOT NULL DEFAULT '[]',
    "read_status" "FeedbackReadStatus" NOT NULL DEFAULT 'UNREAD',
    "agent_acknowledgement_note" TEXT,
    "read_at" TIMESTAMP(3),
    "acknowledged_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "manager_feedback_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "users_email_key" ON "users"("email");

-- CreateIndex
CREATE UNIQUE INDEX "users_external_crm_agent_id_key" ON "users"("external_crm_agent_id");

-- CreateIndex
CREATE INDEX "users_role_is_active_idx" ON "users"("role", "is_active");

-- CreateIndex
CREATE INDEX "users_manager_id_idx" ON "users"("manager_id");

-- CreateIndex
CREATE INDEX "integrations_crm_type_is_active_idx" ON "integrations"("crm_type", "is_active");

-- CreateIndex
CREATE INDEX "tickets_assigned_agent_id_ticket_closed_at_idx" ON "tickets"("assigned_agent_id", "ticket_closed_at" DESC);

-- CreateIndex
CREATE INDEX "tickets_processing_status_idx" ON "tickets"("processing_status");

-- CreateIndex
CREATE INDEX "tickets_ticket_closed_at_idx" ON "tickets"("ticket_closed_at" DESC);

-- CreateIndex
CREATE UNIQUE INDEX "tickets_integration_id_external_ticket_id_ticket_closed_at_key" ON "tickets"("integration_id", "external_ticket_id", "ticket_closed_at");

-- CreateIndex
CREATE UNIQUE INDEX "ai_qa_reports_ticket_id_key" ON "ai_qa_reports"("ticket_id");

-- CreateIndex
CREATE INDEX "ai_qa_reports_agent_score_idx" ON "ai_qa_reports"("agent_score");

-- CreateIndex
CREATE INDEX "ai_qa_reports_is_resolved_properly_premature_closure_detect_idx" ON "ai_qa_reports"("is_resolved_properly", "premature_closure_detected");

-- CreateIndex
CREATE INDEX "ai_qa_reports_issue_category_idx" ON "ai_qa_reports"("issue_category");

-- CreateIndex
CREATE INDEX "manager_feedback_agent_id_read_status_created_at_idx" ON "manager_feedback"("agent_id", "read_status", "created_at" DESC);

-- CreateIndex
CREATE INDEX "manager_feedback_ticket_id_idx" ON "manager_feedback"("ticket_id");

-- AddForeignKey
ALTER TABLE "users" ADD CONSTRAINT "users_manager_id_fkey" FOREIGN KEY ("manager_id") REFERENCES "users"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "tickets" ADD CONSTRAINT "tickets_integration_id_fkey" FOREIGN KEY ("integration_id") REFERENCES "integrations"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "tickets" ADD CONSTRAINT "tickets_assigned_agent_id_fkey" FOREIGN KEY ("assigned_agent_id") REFERENCES "users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ai_qa_reports" ADD CONSTRAINT "ai_qa_reports_ticket_id_fkey" FOREIGN KEY ("ticket_id") REFERENCES "tickets"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "manager_feedback" ADD CONSTRAINT "manager_feedback_ticket_id_fkey" FOREIGN KEY ("ticket_id") REFERENCES "tickets"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "manager_feedback" ADD CONSTRAINT "manager_feedback_manager_id_fkey" FOREIGN KEY ("manager_id") REFERENCES "users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "manager_feedback" ADD CONSTRAINT "manager_feedback_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
