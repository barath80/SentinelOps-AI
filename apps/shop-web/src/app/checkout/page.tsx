import { redirect } from "next/navigation";
import { Suspense } from "react";
import CheckoutForm from "@/components/CheckoutForm";
import { getSession } from "@/lib/session";

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
