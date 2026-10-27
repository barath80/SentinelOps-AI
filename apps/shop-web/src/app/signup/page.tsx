import { Suspense } from "react";
import AuthForm from "@/components/AuthForm";
import { googleConfigured, safeNext } from "@/lib/session";

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
