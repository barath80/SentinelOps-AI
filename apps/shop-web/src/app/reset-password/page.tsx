import type { Metadata } from "next";
import Link from "next/link";
import ResetPasswordForm from "@/components/ResetPasswordForm";
import { NOINDEX } from "@/lib/seo";

export const metadata: Metadata = { title: "Choose a new password", ...NOINDEX };

export default async function ResetPasswordPage({ searchParams }: PageProps<"/reset-password">) {
  const sp = await searchParams;
  const token = typeof sp.token === "string" ? sp.token : null;
  if (!token) {
    return (
      <div className="mx-auto max-w-sm rounded-lg border border-zinc-200 bg-white p-6 text-center dark:border-zinc-800 dark:bg-zinc-900">
        <h1 className="text-xl font-semibold">Missing reset link</h1>
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">
          This page needs a reset token. <Link href="/forgot-password" className="text-sky-700 hover:underline">Request a new link</Link>.
        </p>
      </div>
    );
  }
  return <ResetPasswordForm token={token} />;
}
