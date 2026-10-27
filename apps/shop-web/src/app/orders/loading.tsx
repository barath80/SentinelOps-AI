import { Skeleton } from "@/components/Skeleton";

export default function Loading() {
  return (
    <>
      <Skeleton className="h-8 w-48" />
      <Skeleton className="mt-2 h-4 w-32" />
      <div className="mt-4 space-y-4">
        {Array.from({ length: 3 }, (_, i) => (
          <div
            key={i}
            className="overflow-hidden rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900"
          >
            <Skeleton className="h-4 w-full" />
            <Skeleton className="mt-3 h-20 w-full" />
          </div>
        ))}
      </div>
    </>
  );
}
