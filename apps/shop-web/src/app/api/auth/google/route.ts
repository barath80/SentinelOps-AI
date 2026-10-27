import { generateCodeVerifier, generateState } from "arctic";
import { cookies } from "next/headers";
import { instrument } from "@/lib/handler";
import { redirect } from "@/lib/authRoutes";
import { GOOGLE_NEXT, GOOGLE_STATE, GOOGLE_VERIFIER, googleClient } from "@/lib/google";
import { cookieSecurity, googleConfigured, safeNext } from "@/lib/session";

// Step 1 of Google sign-in: remember a random state and PKCE verifier, then send the browser
// to Google. Both are checked in the callback, which blocks forged and replayed callbacks.
export const GET = instrument("/api/auth/google", async (req) => {
  if (!googleConfigured()) return redirect("/login?error=google_unavailable");
  const state = generateState();
  const verifier = generateCodeVerifier();
  const url = googleClient(req.url).createAuthorizationURL(state, verifier, ["openid", "profile", "email"]);
  const store = await cookies();
  const short = { ...cookieSecurity(), maxAge: 600 };
  store.set(GOOGLE_STATE, state, short);
  store.set(GOOGLE_VERIFIER, verifier, short);
  store.set(GOOGLE_NEXT, safeNext(new URL(req.url).searchParams.get("next")), short);
  return new Response(null, { status: 302, headers: { location: url.toString() } });
});
