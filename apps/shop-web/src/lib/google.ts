import { Google } from "arctic";

// The redirect URI must exactly match one registered in Google Cloud Console. Set APP_URL
// (e.g. https://shopsphere-demo-beta.vercel.app) so it does not depend on the request host.
export function googleClient(requestUrl: string): Google {
  const origin = (process.env.APP_URL ?? new URL(requestUrl).origin).replace(/\/$/, "");
  return new Google(process.env.AUTH_GOOGLE_ID!, process.env.AUTH_GOOGLE_SECRET!, `${origin}/api/auth/google/callback`);
}

export const GOOGLE_STATE = "g_oauth_state";
export const GOOGLE_VERIFIER = "g_oauth_verifier";
export const GOOGLE_NEXT = "g_oauth_next";
