"use client";
import Link from "next/link";
import { useEffect } from "react";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    // Plain console.error, not lib/log: that module is server-oriented (it also pulls in
    // lib/faults.ts, which imports node:async_hooks) and shouldn't be bundled for the browser.
    console.error("client_error_boundary", { error: error.message, digest: error.digest });
  }, [error]);

  return (
    <div className="mx-auto max-w-lg rounded-lg bg-white p-8 text-center dark:bg-zinc-900">
      <h1 className="text-2xl font-bold">Something went wrong</h1>
      <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">
        We hit an unexpected error loading this page. You can try again, or head back home.
      </p>
      <div className="mt-6 flex justify-center gap-3">
        <button
          type="button"
          onClick={() => reset()}
          className="rounded-full bg-amber-400 px-5 py-2 font-semibold text-zinc-900 hover:bg-amber-300"
        >
          Try again
        </button>
        <Link
          href="/"
          className="rounded-full border border-zinc-300 px-5 py-2 font-semibold hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          Go home
        </Link>
      </div>
    </div>
  );
}
