// ShopSphere catalogue. Synthetic data: brands are invented, images are generated per colour.
// Generated deterministically from a fixed seed so ids, prices and ratings are stable across
// builds. Ids p1..p96 stay stable for the SentinelOps traffic scripts and benchmarks.

export type Color = { name: string; hex: string };
export type ArtKind =
  | "headphones" | "earbuds" | "phone" | "laptop" | "watch" | "camera" | "speaker" | "keyboard"
  | "tshirt" | "hoodie" | "cap" | "backpack" | "sneaker" | "boot" | "lamp" | "chair" | "plant"
  | "mug" | "bottle" | "pan" | "dumbbell" | "ball" | "perfume" | "lipstick" | "jar" | "robot" | "blocks" | "teddy";

export type CategoryId = "electronics" | "fashion" | "footwear" | "home" | "kitchen" | "sports" | "beauty" | "toys";

export type Product = {
  id: string;
  name: string;
  brand: string;
  category: CategoryId;
  art: ArtKind;
  description: string;
  bullets: string[];
  specs: Record<string, string>;
  priceCents: number;
  listPriceCents: number;
  rating: number; // 1 decimal, 1-5
  reviewCount: number;
  boughtLastMonth: number;
  stock: number;
  colors: Color[];
  fastDelivery: boolean;
  badge: "Best Seller" | "Limited deal" | "New arrival" | null;
};

export const CATEGORIES: { id: CategoryId; name: string; blurb: string }[] = [
  { id: "electronics", name: "Electronics", blurb: "Audio, phones, laptops and more" },
  { id: "fashion", name: "Fashion", blurb: "Everyday clothing and accessories" },
  { id: "footwear", name: "Footwear", blurb: "Sneakers, trail and boots" },
  { id: "home", name: "Home", blurb: "Lighting, furniture and decor" },
  { id: "kitchen", name: "Kitchen", blurb: "Cookware and drinkware" },
  { id: "sports", name: "Sports & Outdoors", blurb: "Train, play and explore" },
  { id: "beauty", name: "Beauty", blurb: "Fragrance, skin and colour" },
  { id: "toys", name: "Toys & Games", blurb: "Build, play and learn" },
];

export const PALETTE: Color[] = [
  { name: "Midnight Black", hex: "#1f2937" },
  { name: "Arctic White", hex: "#e5e7eb" },
  { name: "Ocean Blue", hex: "#2563eb" },
  { name: "Crimson Red", hex: "#dc2626" },
  { name: "Forest Green", hex: "#16a34a" },
  { name: "Sunset Orange", hex: "#f97316" },
  { name: "Lavender", hex: "#8b5cf6" },
  { name: "Rose Pink", hex: "#ec4899" },
  { name: "Sand Beige", hex: "#c8a97e" },
  { name: "Slate Grey", hex: "#64748b" },
  { name: "Teal", hex: "#0d9488" },
  { name: "Mustard", hex: "#ca8a04" },
];

type Template = { art: ArtKind; names: string[]; price: [number, number]; bullets: string[]; specs: Record<string, string[]> };

const BRANDS: Record<CategoryId, string[]> = {
  electronics: ["Voltix", "Auralis", "Nimbus Labs", "Pixelon"],
  fashion: ["Northpeak", "Urbanfold", "Linea"],
  footwear: ["Strider", "Trailform", "Northpeak"],
  home: ["Hearthly", "Oakline", "Lumen & Co"],
  kitchen: ["Cuisio", "Brewhaus", "Hearthly"],
  sports: ["Peakform", "Kinetic", "Trailform"],
  beauty: ["Glowra", "Petalwise", "Lune Botanics"],
  toys: ["Brickly", "Playnest", "Orbit Kids"],
};

const TEMPLATES: Record<CategoryId, Template[]> = {
  electronics: [
    { art: "headphones", names: ["Wireless Noise-Cancelling Headphones", "Studio Over-Ear Headphones"], price: [79, 299], bullets: ["Active noise cancelling with transparency mode", "Up to 40 hours of battery life", "Fast charge: 10 minutes for 5 hours", "Multipoint Bluetooth 5.3"], specs: { Connectivity: ["Bluetooth 5.3", "Bluetooth 5.3 + USB-C audio"], Battery: ["40 h", "30 h", "50 h"], Weight: ["250 g", "268 g", "231 g"] } },
    { art: "earbuds", names: ["True Wireless Earbuds", "Sport Earbuds with Ear Hooks"], price: [39, 199], bullets: ["IPX5 sweat and water resistant", "Pocket charging case with USB-C", "Clear calls with 4 microphones", "Customizable touch controls"], specs: { Connectivity: ["Bluetooth 5.3"], Battery: ["8 h + 24 h case", "6 h + 30 h case"], "Water resistance": ["IPX5", "IPX4"] } },
    { art: "phone", names: ["6.5\" Smartphone 128 GB", "Compact Smartphone 256 GB"], price: [249, 899], bullets: ["120 Hz OLED display", "50 MP main camera with night mode", "All-day battery with 45 W charging", "5G and Wi-Fi 6E"], specs: { Storage: ["128 GB", "256 GB"], Display: ["6.5\" OLED", "6.1\" OLED"], Camera: ["50 MP + 12 MP", "48 MP + 12 MP"] } },
    { art: "laptop", names: ["14\" Ultrabook", "16\" Creator Laptop"], price: [649, 1899], bullets: ["Lightweight aluminium body", "Backlit keyboard and large trackpad", "Up to 14 hours of battery", "Two USB-C with fast charging"], specs: { Memory: ["16 GB", "32 GB"], Storage: ["512 GB SSD", "1 TB SSD"], Display: ["14\" 2.8K", "16\" 3.2K"] } },
    { art: "watch", names: ["Smart Fitness Watch", "GPS Running Watch"], price: [59, 349], bullets: ["Heart rate, sleep and SpO2 tracking", "Built-in GPS", "Water resistant to 50 m", "Up to 10 days of battery"], specs: { Display: ["1.4\" AMOLED", "1.2\" AMOLED"], "Water resistance": ["5 ATM"], Battery: ["10 days", "7 days"] } },
    { art: "camera", names: ["Mirrorless Camera Kit", "Compact Travel Camera"], price: [399, 1499], bullets: ["24 MP sensor with fast autofocus", "4K video at 30 fps", "Flip screen for vlogging", "Includes 18-55 mm lens"], specs: { Sensor: ["24 MP APS-C", "20 MP 1-inch"], Video: ["4K 30p", "4K 60p"] } },
    { art: "speaker", names: ["Portable Bluetooth Speaker", "Smart Home Speaker"], price: [29, 249], bullets: ["Room-filling 360° sound", "Waterproof IP67", "Up to 20 hours of play", "Pair two for stereo"], specs: { Output: ["20 W", "40 W"], Battery: ["20 h", "12 h"] } },
    { art: "keyboard", names: ["Mechanical Keyboard", "Low-Profile Wireless Keyboard"], price: [49, 199], bullets: ["Hot-swappable switches", "Per-key RGB backlight", "Wired, Bluetooth and 2.4 GHz", "Aluminium top plate"], specs: { Layout: ["75%", "Full size", "TKL"], Switches: ["Tactile", "Linear"] } },
  ],
  fashion: [
    { art: "tshirt", names: ["Organic Cotton T-Shirt", "Relaxed Fit Graphic Tee"], price: [14, 39], bullets: ["100% organic cotton", "Pre-shrunk, soft wash", "Regular fit", "Machine washable"], specs: { Material: ["Organic cotton"], Fit: ["Regular", "Relaxed"] } },
    { art: "hoodie", names: ["Fleece Pullover Hoodie", "Zip-Up Tech Hoodie"], price: [29, 89], bullets: ["Brushed fleece interior", "Kangaroo pocket", "Ribbed cuffs and hem", "Recycled polyester blend"], specs: { Material: ["Cotton/poly fleece", "Recycled polyester"], Fit: ["Regular"] } },
    { art: "cap", names: ["Classic Baseball Cap", "Packable Sun Hat"], price: [12, 35], bullets: ["Adjustable strap", "Breathable cotton twill", "Curved brim", "One size fits most"], specs: { Material: ["Cotton twill", "Nylon"] } },
    { art: "backpack", names: ["Everyday Laptop Backpack", "Roll-Top Travel Backpack"], price: [39, 129], bullets: ["Padded 16\" laptop sleeve", "Water-resistant fabric", "Luggage pass-through", "Hidden anti-theft pocket"], specs: { Capacity: ["24 L", "30 L"], Material: ["Recycled nylon"] } },
  ],
  footwear: [
    { art: "sneaker", names: ["Everyday Running Shoes", "Knit Lifestyle Sneakers"], price: [49, 159], bullets: ["Responsive foam midsole", "Breathable engineered mesh", "Durable rubber outsole", "Removable cushioned insole"], specs: { Drop: ["8 mm", "10 mm"], Weight: ["265 g", "290 g"] } },
    { art: "boot", names: ["Waterproof Hiking Boots", "Leather Chelsea Boots"], price: [79, 219], bullets: ["Waterproof membrane", "Grippy lugged outsole", "Cushioned ankle collar", "Leather and textile upper"], specs: { Upper: ["Leather", "Suede"], Waterproof: ["Yes"] } },
  ],
  home: [
    { art: "lamp", names: ["LED Desk Lamp", "Arc Floor Lamp"], price: [24, 189], bullets: ["Dimmable warm to cool light", "Touch controls", "Energy-efficient LED", "Adjustable arm"], specs: { "Colour temperature": ["2700-6500 K"], Power: ["10 W", "18 W"] } },
    { art: "chair", names: ["Ergonomic Office Chair", "Accent Lounge Chair"], price: [119, 449], bullets: ["Adjustable lumbar support", "Breathable mesh back", "4D armrests", "Supports up to 130 kg"], specs: { Material: ["Mesh", "Bouclé fabric"], "Max load": ["130 kg"] } },
    { art: "plant", names: ["Ceramic Plant Pot Set", "Self-Watering Planter"], price: [15, 69], bullets: ["Drainage hole with saucer", "Glazed ceramic", "Set of three sizes", "Indoor and outdoor"], specs: { Material: ["Ceramic"], Sizes: ["S / M / L"] } },
  ],
  kitchen: [
    { art: "mug", names: ["Insulated Travel Mug", "Stoneware Coffee Mug Set"], price: [12, 45], bullets: ["Keeps drinks hot for 6 hours", "Leak-proof lid", "Dishwasher safe", "Fits most cup holders"], specs: { Capacity: ["350 ml", "470 ml"], Material: ["Stainless steel", "Stoneware"] } },
    { art: "bottle", names: ["Insulated Water Bottle", "Glass Infuser Bottle"], price: [14, 49], bullets: ["Cold for 24 hours, hot for 12", "BPA-free", "Wide mouth for ice", "Powder-coated grip"], specs: { Capacity: ["750 ml", "1 L"], Material: ["Stainless steel", "Borosilicate glass"] } },
    { art: "pan", names: ["Non-Stick Frying Pan", "Cast Iron Skillet"], price: [24, 89], bullets: ["PFAS-free ceramic coating", "Works on induction", "Oven safe to 230 °C", "Stay-cool handle"], specs: { Diameter: ["24 cm", "28 cm"], Hob: ["All incl. induction"] } },
  ],
  sports: [
    { art: "dumbbell", names: ["Adjustable Dumbbell Pair", "Neoprene Dumbbell Set"], price: [29, 299], bullets: ["Quick-change weight dial", "Anti-roll design", "Comfortable knurled grip", "Space-saving storage tray"], specs: { Range: ["2-24 kg", "1-5 kg set"] } },
    { art: "ball", names: ["Match Football", "Indoor Basketball"], price: [19, 59], bullets: ["Durable stitched panels", "Consistent bounce", "All-weather cover", "Official size and weight"], specs: { Size: ["5", "7"] } },
    { art: "bottle", names: ["Sports Squeeze Bottle", "Hydration Flask"], price: [9, 39], bullets: ["One-hand flip cap", "Measurement markings", "Odour resistant", "Fits bike cages"], specs: { Capacity: ["600 ml", "1 L"] } },
  ],
  beauty: [
    { art: "perfume", names: ["Eau de Parfum 50 ml", "Fresh Citrus Eau de Toilette"], price: [29, 129], bullets: ["Long-lasting fragrance", "Notes of bergamot, amber and musk", "Vegan and cruelty-free", "Refillable bottle"], specs: { Volume: ["50 ml", "100 ml"] } },
    { art: "lipstick", names: ["Satin Lipstick", "Hydrating Tinted Lip Balm"], price: [9, 35], bullets: ["Rich, buildable colour", "Infused with shea butter", "Lasts up to 8 hours", "Cruelty-free"], specs: { Finish: ["Satin", "Matte", "Sheer"] } },
    { art: "jar", names: ["Daily Moisturizer SPF 30", "Overnight Repair Cream"], price: [14, 79], bullets: ["Hyaluronic acid and niacinamide", "Non-comedogenic", "Fragrance-free", "Suitable for sensitive skin"], specs: { Volume: ["50 ml"], "Skin type": ["All", "Dry", "Combination"] } },
  ],
  toys: [
    { art: "robot", names: ["Coding Robot Kit", "Remote Control Robot"], price: [39, 149], bullets: ["Teaches coding through play", "App and screen-free modes", "Rechargeable battery", "Ages 8+"], specs: { Age: ["8+", "6+"], Battery: ["Rechargeable"] } },
    { art: "blocks", names: ["Building Blocks Set 500 pcs", "Magnetic Tiles 100 pcs"], price: [19, 89], bullets: ["Compatible with major brick systems", "Storage box included", "Non-toxic ABS", "Ages 4+"], specs: { Pieces: ["500", "100", "250"], Age: ["4+", "3+"] } },
    { art: "teddy", names: ["Plush Teddy Bear", "Cuddly Bunny Plush"], price: [12, 49], bullets: ["Super soft plush", "Safety embroidered eyes", "Surface washable", "Suitable from birth"], specs: { Height: ["30 cm", "45 cm"] } },
  ],
};

// mulberry32: tiny deterministic PRNG so the catalogue is identical on every build.
function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Lower-case only an ordinary capitalised first word, so acronyms like GPS or USB-C stay intact.
const lowerFirst = (s: string) => (/^[A-Z][a-z]/.test(s) ? s[0].toLowerCase() + s.slice(1) : s);

const PER_CATEGORY = 12;

function buildCatalogue(): Product[] {
  const r = rng(20261027);
  const pick = <T,>(xs: T[]) => xs[Math.floor(r() * xs.length)];
  const out: Product[] = [];
  let n = 0;
  CATEGORIES.forEach((cat, ci) => {
    const templates = TEMPLATES[cat.id];
    for (let i = 0; i < PER_CATEGORY; i++) {
      n++;
      const t = templates[i % templates.length];
      const brand = BRANDS[cat.id][(i + ci) % BRANDS[cat.id].length];
      const baseName = t.names[Math.floor(i / templates.length) % t.names.length];
      const [lo, hi] = t.price;
      const price = Math.round((lo + r() * (hi - lo)) * 100 / 100) * 100 - 1; // ends in .99
      const discount = r() < 0.55 ? 0.05 + r() * 0.35 : 0;
      const listPrice = discount ? Math.round(price / (1 - discount) / 100) * 100 - 1 : price;
      const nColors = 2 + Math.floor(r() * 4);
      const start = Math.floor(r() * PALETTE.length);
      // Step 5 is coprime with the 12-colour palette, so up to 12 picks never repeat a colour.
      const colors = Array.from({ length: nColors }, (_, k) => PALETTE[(start + k * 5) % PALETTE.length]);
      const rating = Math.round((3.4 + r() * 1.55) * 10) / 10;
      const reviewCount = Math.floor(20 + Math.pow(r(), 2) * 24000);
      const specs: Record<string, string> = { Brand: brand };
      for (const [k, vs] of Object.entries(t.specs)) specs[k] = pick(vs);
      out.push({
        id: `p${n}`,
        name: `${brand} ${baseName}`,
        brand,
        category: cat.id,
        art: t.art,
        description: `${baseName} from ${brand}. ${t.bullets[0]}, ${lowerFirst(t.bullets[1])}, and ${lowerFirst(t.bullets[2])}. Designed for everyday use and backed by a 2-year warranty.`,
        bullets: t.bullets,
        specs,
        priceCents: price,
        listPriceCents: Math.max(listPrice, price),
        rating: Math.min(5, rating),
        reviewCount,
        boughtLastMonth: Math.floor(Math.pow(r(), 3) * 5000),
        stock: Math.floor(r() * 120),
        colors,
        fastDelivery: r() < 0.7,
        badge: null,
      });
    }
  });
  // Same brand + same product name would look like a duplicate listing: give repeats a model variant.
  const VARIANTS = ["Pro", "Lite", "Plus", "Max", "Air", "Sport", "Mini", "Ultra"];
  const seen = new Set<string>();
  for (const p of out) {
    let name = p.name;
    for (let v = 0; seen.has(name) && v < VARIANTS.length; v++) name = `${p.name} ${VARIANTS[v]}`;
    seen.add(name);
    p.name = name;
  }
  // Badges from the data itself: the most bought per category, the deepest discounts, a few new ones.
  for (const cat of CATEGORIES) {
    const inCat = out.filter((p) => p.category === cat.id);
    inCat.sort((a, b) => b.boughtLastMonth - a.boughtLastMonth)[0].badge = "Best Seller";
  }
  out.filter((p) => !p.badge).sort((a, b) => discountPct(b) - discountPct(a)).slice(0, 8).forEach((p) => (p.badge = "Limited deal"));
  out.filter((p) => !p.badge && p.reviewCount < 200).slice(0, 6).forEach((p) => (p.badge = "New arrival"));
  return out;
}

export const PRODUCTS: Product[] = buildCatalogue();
export const BRAND_NAMES = [...new Set(PRODUCTS.map((p) => p.brand))].sort();

export function discountPct(p: Product): number {
  return p.listPriceCents > p.priceCents ? Math.round((1 - p.priceCents / p.listPriceCents) * 100) : 0;
}

export function getProduct(id: string): Product | undefined {
  return PRODUCTS.find((p) => p.id === id);
}

export function colorOf(p: Product, name?: string | null): Color {
  return p.colors.find((c) => c.name === name) ?? p.colors[0];
}

export type SortKey = "relevance" | "price-asc" | "price-desc" | "rating" | "reviews" | "bestsellers";

export type SearchQuery = {
  q?: string;
  category?: string;
  brand?: string;
  minCents?: number;
  maxCents?: number;
  minRating?: number;
  sort?: SortKey;
};

export function searchProducts(query: SearchQuery): Product[] {
  const terms = (query.q ?? "").toLowerCase().split(/\s+/).filter(Boolean);
  const scored = PRODUCTS.map((p) => {
    const hay = `${p.name} ${p.brand} ${p.category} ${p.description} ${p.colors.map((c) => c.name).join(" ")}`.toLowerCase();
    const score = terms.reduce((s, t) => s + (p.name.toLowerCase().includes(t) ? 3 : hay.includes(t) ? 1 : 0), 0);
    return { p, score };
  }).filter(({ p, score }) =>
    (!terms.length || score >= terms.length) &&
    (!query.category || p.category === query.category) &&
    (!query.brand || p.brand === query.brand) &&
    (query.minCents === undefined || p.priceCents >= query.minCents) &&
    (query.maxCents === undefined || p.priceCents <= query.maxCents) &&
    (query.minRating === undefined || p.rating >= query.minRating));
  const by: Record<SortKey, (a: (typeof scored)[0], b: (typeof scored)[0]) => number> = {
    relevance: (a, b) => b.score - a.score || b.p.boughtLastMonth - a.p.boughtLastMonth,
    "price-asc": (a, b) => a.p.priceCents - b.p.priceCents,
    "price-desc": (a, b) => b.p.priceCents - a.p.priceCents,
    rating: (a, b) => b.p.rating - a.p.rating || b.p.reviewCount - a.p.reviewCount,
    reviews: (a, b) => b.p.reviewCount - a.p.reviewCount,
    bestsellers: (a, b) => b.p.boughtLastMonth - a.p.boughtLastMonth,
  };
  return scored.sort(by[query.sort ?? "relevance"]).map(({ p }) => p);
}

// Kept for older callers (and the SentinelOps traffic scripts' ?q= search).
export function listProducts(query?: string): Product[] {
  return searchProducts({ q: query });
}

export function formatPrice(cents: number): string {
  return `$${(cents / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatCount(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, "")}K` : String(n);
}
