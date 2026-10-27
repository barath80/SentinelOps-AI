import { log } from "./log";

// EMAIL_PROVIDER=console (default) logs the message instead of sending it, so dev/test never
// needs a real provider configured. Set EMAIL_PROVIDER=resend + RESEND_API_KEY to send for real.
export async function sendEmail(to: string, subject: string, text: string): Promise<void> {
  if (process.env.EMAIL_PROVIDER === "resend") {
    const apiKey = process.env.RESEND_API_KEY;
    if (!apiKey) throw new Error("RESEND_API_KEY is not set");
    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${apiKey}` },
      body: JSON.stringify({ from: "ShopSphere <no-reply@shopsphere.example>", to, subject, text }),
    });
    if (!res.ok) throw new Error(`resend_send_failed:${res.status}`);
    return;
  }
  log("info", "email_console", { to, subject, text });
}
