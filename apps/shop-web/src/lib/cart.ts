import { cookies } from "next/headers";
import { colorOf, getProduct, type Color, type Product } from "./products";

// The cart lives in a cookie so the app stays stateless on serverless hosting.
// A line is a product in one colour; the same product in two colours is two lines.
export type CartLine = { id: string; qty: number; color?: string };
export type DetailedLine = { product: Product; qty: number; color: Color; lineCents: number };

const COOKIE = "cart";
const MAX_LINES = 20;
const MAX_QTY = 10;

export async function readCart(): Promise<CartLine[]> {
  const store = await cookies();
  const raw = store.get(COOKIE)?.value;
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (l): l is CartLine =>
          typeof l?.id === "string" && Number.isInteger(l?.qty) && l.qty > 0 && !!getProduct(l.id),
      )
      .slice(0, MAX_LINES)
      .map((l) => {
        const p = getProduct(l.id)!;
        return { id: l.id, qty: Math.min(l.qty, MAX_QTY), color: colorOf(p, typeof l.color === "string" ? l.color : null).name };
      });
  } catch {
    return [];
  }
}

export async function writeCart(lines: CartLine[]): Promise<void> {
  const store = await cookies();
  store.set(COOKIE, JSON.stringify(lines), {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 7,
  });
}

export const sameLine = (a: CartLine, id: string, color: string) => a.id === id && a.color === color;

export function detail(lines: CartLine[]): { lines: DetailedLine[]; totalCents: number; count: number } {
  const detailed = lines.flatMap((l) => {
    const product = getProduct(l.id);
    return product ? [{ product, qty: l.qty, color: colorOf(product, l.color), lineCents: product.priceCents * l.qty }] : [];
  });
  return {
    lines: detailed,
    totalCents: detailed.reduce((s, l) => s + l.lineCents, 0),
    count: detailed.reduce((s, l) => s + l.qty, 0),
  };
}

export { MAX_QTY };
