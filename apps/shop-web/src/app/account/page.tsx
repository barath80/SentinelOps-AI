import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { listAddresses } from "@/lib/addresses";
import AddressesManager from "@/components/AddressesManager";
import PasswordForm from "@/components/PasswordForm";
import ProfileForm from "@/components/ProfileForm";
import { NOINDEX } from "@/lib/seo";
import { getSession } from "@/lib/session";

export const metadata: Metadata = { title: "Account settings", ...NOINDEX };

async function Account() {
  const session = await getSession();
  if (!session) redirect("/login?next=/account");
  const addresses = await listAddresses(session.userId);

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-2xl font-bold">Account settings</h1>
      <ProfileForm name={session.name} email={session.email} />
      <PasswordForm />
      <AddressesManager initial={addresses} />
    </div>
  );
}

export default function AccountPage() {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <Account />
    </Suspense>
  );
}
