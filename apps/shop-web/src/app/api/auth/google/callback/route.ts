import { decodeIdToken, OAuth2RequestError } from "arctic";
import { cookies } from "next/headers";
import { instrument } from "@/lib/handler";
import { redirect } from "@/lib/authRoutes";
import { GOOGLE_NEXT, GOOGLE_STATE, GOOGLE_VERIFIER, googleClient } from "@/lib/google";
import { createSession, googleConfigured, safeNext } from "@/lib/session";
import { upsertGoogleUser } from "@/lib/users";
import { log } from "@/lib/log";

type Claims = { sub: string; email?: string; email_verified?: boolean; name?: string };

// Step 2: Google sends the browser back with ?code&state. The ID token comes straight from
// Google's token endpoint over TLS, so decoding it without a separate signature check is the
// standard OIDC code-flow practice.
export const GET = instrument("/api/auth/google/callback", async (req, _ctx, requestId) => {
  if (!googleConfigured()) return redirect("/login?error=google_unavailable");
  const params = new URL(req.url).searchParams;
  const store = await cookies();
  const expected = store.get(GOOGLE_STATE)?.value;
  const verifier = store.get(GOOGLE_VERIFIER)?.value;
  const next = safeNext(store.get(GOOGLE_NEXT)?.value);
  for (const c of [GOOGLE_STATE, GOOGLE_VERIFIER, GOOGLE_NEXT]) store.delete(c);

  const code = params.get("code");
  if (!code || !expected || !verifier || params.get("state") !== expected) return redirect("/login?error=google_state");

  try {
    const tokens = await googleClient(req.url).validateAuthorizationCode(code, verifier);
    const claims = decodeIdToken(tokens.idToken()) as Claims;
    const user = await upsertGoogleUser({ sub: claims.sub, email: claims.email, emailVerified: claims.email_verified, name: claims.name });
    await createSession({ userId: user.id, name: user.name, email: user.email });
    return redirect(next);
  } catch (err) {
    const reason = err instanceof OAuth2RequestError ? "google_rejected" : err instanceof Error && err.message === "google_email_not_verified" ? "google_unverified" : "google_failed";
    log("warning", "google_sign_in_failed", { request_id: requestId, reason });
    return redirect(`/login?error=${reason}`);
  }
});
