import type { Metadata } from "next";
import { NOINDEX } from "@/lib/seo";

export const metadata: Metadata = { title: "Your cart", ...NOINDEX };

export default function CartLayout({ children }: LayoutProps<"/cart">) {
  return children;
}
