"use client";
import { useState } from "react";

export default function AddToCart({ productId }: { productId: string }) {
  const [state, setState] = useState<"idle" | "busy" | "added" | "error">("idle");

  async function add() {
    setState("busy");
    try {
      const cur = await fetch("/api/cart").then((r) => r.json());
      const existing = cur.lines.find((l: { product: { id: string }; qty: number }) => l.product.id === productId);
      const res = await fetch("/api/cart", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ id: productId, qty: Math.min((existing?.qty ?? 0) + 1, 10) }),
      });
      setState(res.ok ? "added" : "error");
    } catch {
      setState("error");
    }
  }

  return (
    <button
      onClick={add}
      disabled={state === "busy"}
      className="rounded bg-black px-3 py-2 text-sm text-white disabled:opacity-50 dark:bg-white dark:text-black"
    >
      {state === "added" ? "Added ✓" : state === "error" ? "Failed, retry" : "Add to cart"}
    </button>
  );
}
