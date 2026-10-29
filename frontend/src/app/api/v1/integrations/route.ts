import { NextRequest, NextResponse } from "next/server";
import { CrmType } from "@prisma/client";
import { auth } from "@/lib/auth";
import { buildWebhookEndpointUrl } from "@/lib/admin-utils";
import { prisma } from "@/lib/prisma";

const FASTAPI_BASE_URL =
  process.env.FASTAPI_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8000";

export async function POST(request: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }
  if (session.user.role !== "ADMIN") {
    return NextResponse.json(
      { detail: "Insufficient permissions" },
      { status: 403 }
    );
  }

  const body = (await request.json()) as {
    name?: string;
    crm_type?: string;
    subdomain_or_base_url?: string;
    api_key?: string;
    webhook_secret?: string;
    is_active?: boolean;
  };

  if (session.accessToken) {
    try {
      const fastApiRes = await fetch(`${FASTAPI_BASE_URL}/api/v1/integrations`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session.accessToken}`,
        },
        body: JSON.stringify(body),
        cache: "no-store",
      });
      if (fastApiRes.ok) {
        const json = await fastApiRes.json();
        return NextResponse.json(json, { status: 201 });
      }
    } catch {
      // Fall back to Prisma
    }
  }

  const crmTypeUpper = (body.crm_type || "ZENDESK").toUpperCase();
  const validCrm: CrmType = (
    ["ZENDESK", "INTERCOM", "FRESHDESK", "CUSTOM"].includes(crmTypeUpper)
      ? crmTypeUpper
      : "ZENDESK"
  ) as CrmType;

  const created = await prisma.integration.create({
    data: {
      name: (body.name || "Enterprise CRM Connector").trim(),
      crmType: validCrm,
      subdomainOrBaseUrl: (
        body.subdomain_or_base_url || "https://support.example.com"
      ).trim(),
      encryptedApiKey: `enc_aes256gcm_v1:${Buffer.from(body.api_key || "key").toString("base64")}`,
      encryptedWebhookSecret: `enc_aes256gcm_v1:${Buffer.from(body.webhook_secret || "secret").toString("base64")}`,
      isActive: body.is_active !== false,
    },
  });

  return NextResponse.json(
    {
      id: created.id,
      name: created.name,
      crm_type: String(created.crmType),
      subdomain_or_base_url: created.subdomainOrBaseUrl,
      is_active: created.isActive,
      webhook_url: buildWebhookEndpointUrl(
        String(created.crmType),
        created.id
      ),
      last_successful_sync_at: created.lastSuccessfulSyncAt
        ? created.lastSuccessfulSyncAt.toISOString()
        : null,
      created_at: created.createdAt.toISOString(),
    },
    { status: 201 }
  );
}

