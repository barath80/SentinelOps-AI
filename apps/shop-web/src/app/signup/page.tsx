import type { Metadata } from "next";
import { Suspense } from "react";
import AuthForm from "@/components/AuthForm";
import { NOINDEX } from "@/lib/seo";
import { googleConfigured, safeNext } from "@/lib/session";

export const metadata: Metadata = { title: "Create an account", ...NOINDEX };

async function Signup({ searchParams }: Pick<PageProps<"/signup">, "searchParams">) {
  const sp = await searchParams;
  const next = safeNext(typeof sp.next === "string" ? sp.next : null);
  return <AuthForm mode="signup" next={next} google={googleConfigured()} />;
}

export default function SignupPage({ searchParams }: PageProps<"/signup">) {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <Signup searchParams={searchParams} />
    </Suspense>
  );
}
