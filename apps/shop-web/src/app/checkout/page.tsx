import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import CheckoutForm from "@/components/CheckoutForm";
import { NOINDEX } from "@/lib/seo";
import { getSession } from "@/lib/session";

export const metadata: Metadata = { title: "Checkout", ...NOINDEX };

async function Gate() {
  const session = await getSession();
  if (!session) redirect("/login?next=/checkout");
  return <CheckoutForm defaultName={session.name} />;
}

export default function CheckoutPage() {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <Gate />
    </Suspense>
  );
}
