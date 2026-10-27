import { instrument } from "@/lib/handler";
import { rateLimitAuth, requireAuthConfig } from "@/lib/authRoutes";
import { sendEmail } from "@/lib/email";
import { createResetToken } from "@/lib/passwordReset";
import { siteUrl } from "@/lib/seo";

// Body: { email }. Always returns 200 regardless of whether the email exists, so this endpoint
// can't be used to enumerate accounts.
export const POST = instrument("/api/auth/forgot-password", async (req) => {
  const off = requireAuthConfig();
  if (off) return off;
  const limited = await rateLimitAuth(req, "forgot-password", 5, 300);
  if (limited) return limited;
  const body = (await req.json().catch(() => null)) as { email?: unknown } | null;
  if (typeof body?.email !== "string") return Response.json({ error: "invalid_input" }, { status: 400 });

  const token = await createResetToken(body.email);
  if (token) {
    const link = `${siteUrl()}/reset-password?token=${token}`;
    await sendEmail(body.email, "Reset your ShopSphere password", `Reset your password: ${link}\nThis link expires in 1 hour.`);
  }
  return Response.json({ ok: true });
});
