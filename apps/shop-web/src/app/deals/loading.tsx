import { ProductGridSkeleton, Skeleton } from "@/components/Skeleton";

export default function Loading() {
  return (
    <>
      <Skeleton className="h-8 w-56" />
      <Skeleton className="mt-2 h-4 w-72" />
      <ProductGridSkeleton count={12} className="grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6" />
    </>
  );
}
