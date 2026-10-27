import Link from "next/link";
import type { ReactNode } from "react";

export default function EmptyState({
  title,
  message,
  action,
  icon,
}: {
  title: string;
  message: ReactNode;
  action?: { href: string; label: string };
  icon?: ReactNode;
}) {
  return (
    <div className="rounded-lg bg-white p-8 text-center dark:bg-zinc-900">
      {icon && <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center text-zinc-400">{icon}</div>}
      <h1 className="text-xl font-bold">{title}</h1>
      <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">{message}</p>
      {action && (
        <Link
          href={action.href}
          className="mt-5 inline-block rounded-full bg-amber-400 px-5 py-2 font-semibold text-zinc-900 hover:bg-amber-300"
        >
          {action.label}
        </Link>
      )}
    </div>
  );
}
