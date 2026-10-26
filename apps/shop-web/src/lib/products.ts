export type Product = {
  id: string;
  name: string;
  description: string;
  priceCents: number;
  stock: number;
  category: string;
};

// Seeded demo catalogue. Synthetic data only.
export const PRODUCTS: Product[] = [
  { id: "p1", name: "Trail Running Shoes", description: "Lightweight shoes with grippy soles.", priceCents: 8900, stock: 40, category: "Footwear" },
  { id: "p2", name: "Insulated Water Bottle", description: "750 ml, keeps drinks cold for 24 hours.", priceCents: 2400, stock: 120, category: "Outdoors" },
  { id: "p3", name: "Wireless Earbuds", description: "Noise-reducing earbuds with 20 h battery.", priceCents: 5900, stock: 65, category: "Electronics" },
  { id: "p4", name: "Canvas Backpack", description: "24 L daypack with laptop sleeve.", priceCents: 4500, stock: 30, category: "Bags" },
  { id: "p5", name: "Mechanical Keyboard", description: "Hot-swappable tactile switches.", priceCents: 11900, stock: 18, category: "Electronics" },
  { id: "p6", name: "Merino Wool Socks", description: "Three-pair pack, all-season.", priceCents: 1800, stock: 200, category: "Apparel" },
];

export function listProducts(query?: string): Product[] {
  const q = query?.trim().toLowerCase();
  if (!q) return PRODUCTS;
  return PRODUCTS.filter(
    (p) => p.name.toLowerCase().includes(q) || p.category.toLowerCase().includes(q),
  );
}

export function getProduct(id: string): Product | undefined {
  return PRODUCTS.find((p) => p.id === id);
}

export function formatPrice(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}
