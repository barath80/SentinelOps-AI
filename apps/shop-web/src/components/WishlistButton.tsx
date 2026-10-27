"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";

export default function WishlistButton({ productId, initial, signedIn }: { productId: string; initial: boolean; signedIn: boolean }) {
  const router = useRouter();
  const [on, setOn] = useState(initial);
  const [busy, setBusy] = useState(false);

  async function toggle() {
    if (!signedIn) {
      router.push(`/login?next=${encodeURIComponent(`/products/${productId}`)}`);
      return;
    }
    setBusy(true);
    const res = on
      ? await fetch(`/api/wishlist/${productId}`, { method: "DELETE" }).catch(() => null)
      : await fetch("/api/wishlist", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ productId }),
        }).catch(() => null);
    setBusy(false);
    if (res?.ok) setOn(!on);
  }

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={busy}
      aria-pressed={on}
      aria-label={on ? "Remove from wishlist" : "Add to wishlist"}
      className="flex items-center gap-1.5 text-sm text-zinc-600 hover:text-rose-600 disabled:opacity-60 dark:text-zinc-300"
    >
      <svg width="20" height="20" viewBox="0 0 24 24" fill={on ? "#e11d48" : "none"} stroke={on ? "#e11d48" : "currentColor"} strokeWidth="1.8" aria-hidden="true">
        <path d="M12 20.5s-7-4.6-9.5-9A5 5 0 0 1 12 6a5 5 0 0 1 9.5 5.5C19 15.9 12 20.5 12 20.5Z" />
      </svg>
      {on ? "Saved" : "Save for later"}
    </button>
  );
}
