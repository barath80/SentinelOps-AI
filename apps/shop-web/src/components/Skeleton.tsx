export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-zinc-200 dark:bg-zinc-800 ${className}`} />;
}

export function ProductCardSkeleton() {
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
      <Skeleton className="aspect-square w-full" />
      <Skeleton className="h-3 w-1/3" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="mt-auto h-6 w-1/2" />
    </li>
  );
}

export function ProductGridSkeleton({
  count = 12,
  className = "grid-cols-2 sm:grid-cols-3 xl:grid-cols-4",
}: {
  count?: number;
  className?: string;
}) {
  return (
    <ul className={`mt-4 grid gap-3 ${className}`}>
      {Array.from({ length: count }, (_, i) => (
        <ProductCardSkeleton key={i} />
      ))}
    </ul>
  );
}
