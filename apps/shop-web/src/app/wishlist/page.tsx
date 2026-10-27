import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import EmptyState from "@/components/EmptyState";
import ProductCard from "@/components/ProductCard";
import { getProduct } from "@/lib/products";
import { NOINDEX } from "@/lib/seo";
import { getSession } from "@/lib/session";
import { listWishlistProductIds } from "@/lib/wishlist";

export const metadata: Metadata = { title: "Your wishlist", ...NOINDEX };

async function Wishlist() {
  const session = await getSession();
  if (!session) redirect("/login?next=/wishlist");
  const ids = await listWishlistProductIds(session.userId);
  const products = ids.flatMap((id) => {
    const p = getProduct(id);
    return p ? [p] : [];
  });

  return (
    <>
      <h1 className="text-2xl font-bold">Your wishlist</h1>
      <p className="text-sm text-zinc-500">{products.length} item{products.length === 1 ? "" : "s"} saved</p>
      {products.length === 0 ? (
        <div className="mt-4">
          <EmptyState
            title="Your wishlist is empty"
            message="Save items you're interested in so you can find them again later."
            action={{ href: "/", label: "Start browsing" }}
          />
        </div>
      ) : (
        <ul className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
          {products.map((p) => <ProductCard key={p.id} p={p} />)}
        </ul>
      )}
    </>
  );
}

export default function WishlistPage() {
  return (
    <Suspense fallback={<p>Loading your wishlist…</p>}>
      <Wishlist />
    </Suspense>
  );
}
