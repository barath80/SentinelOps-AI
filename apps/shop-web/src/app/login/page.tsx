import type { Metadata } from "next";
import { Suspense } from "react";
import AuthForm from "@/components/AuthForm";
import { NOINDEX } from "@/lib/seo";
import { googleConfigured, safeNext } from "@/lib/session";

export const metadata: Metadata = { title: "Sign in", ...NOINDEX };

async function Login({ searchParams }: Pick<PageProps<"/login">, "searchParams">) {
  const sp = await searchParams;
  const next = safeNext(typeof sp.next === "string" ? sp.next : null);
  const error = typeof sp.error === "string" ? sp.error : undefined;
  return <AuthForm mode="login" next={next} error={error} google={googleConfigured()} />;
}

export default function LoginPage({ searchParams }: PageProps<"/login">) {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <Login searchParams={searchParams} />
    </Suspense>
  );
}
