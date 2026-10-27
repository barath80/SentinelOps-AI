import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-lg rounded-lg bg-white p-8 text-center dark:bg-zinc-900">
      <h1 className="text-3xl font-bold">Page not found</h1>
      <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">
        We couldn&apos;t find what you were looking for. It may have been moved, or it never existed.
      </p>
      <div className="mt-6 flex justify-center gap-3">
        <Link href="/" className="rounded-full bg-amber-400 px-5 py-2 font-semibold text-zinc-900 hover:bg-amber-300">
          Back to home
        </Link>
        <Link
          href="/search"
          className="rounded-full border border-zinc-300 px-5 py-2 font-semibold hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          Browse products
        </Link>
      </div>
    </div>
  );
}
