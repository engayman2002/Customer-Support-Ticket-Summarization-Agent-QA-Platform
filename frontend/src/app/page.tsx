import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { getHomeDashboardForRole } from "@/middleware";

export default async function RootPage() {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }
  redirect(getHomeDashboardForRole(session.user.role));
}

