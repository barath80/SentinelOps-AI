import type { Metadata } from "next";
import { Suspense } from "react";
import CheckoutForm from "@/components/CheckoutForm";
import { NOINDEX } from "@/lib/seo";
import { getSession } from "@/lib/session";

export const metadata: Metadata = { title: "Checkout", ...NOINDEX };

// Guest checkout stays available in the UI (the API has always supported it, since the
// SentinelOps traffic generator uses it): a signed-out visitor sees a sign-in prompt plus the
// option to continue as a guest, rather than being redirected away.
async function Gate() {
  const session = await getSession();
  return <CheckoutForm defaultName={session?.name ?? ""} signedIn={!!session} />;
}

export default function CheckoutPage() {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <Gate />
    </Suspense>
  );
}
