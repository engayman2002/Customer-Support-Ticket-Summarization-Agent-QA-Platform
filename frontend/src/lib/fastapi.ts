export async function fetchFastApiCurrentUser(
  accessToken: string
): Promise<Record<string, unknown> | null> {
  if (!accessToken) {
    return null;
  }

  const baseUrl =
    process.env.FASTAPI_INTERNAL_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";

  try {
    const response = await fetch(`${baseUrl}/api/v1/auth/me`, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
      cache: "no-store",
    });

    if (!response.ok) {
      return {
        status: response.status,
        error: `FastAPI returned HTTP ${response.status}`,
      };
    }

    return (await response.json()) as Record<string, unknown>;
  } catch {
    return null;
  }
}

