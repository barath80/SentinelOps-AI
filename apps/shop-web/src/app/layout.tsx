import type { Metadata } from "next";
import Link from "next/link";
import { Geist } from "next/font/google";
import Header from "@/components/Header";
import { CATEGORIES } from "@/lib/products";
import { SITE_DESCRIPTION, SITE_NAME, siteUrl } from "@/lib/seo";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl()),
  title: { default: `${SITE_NAME}: shop electronics, fashion, home and more`, template: `%s | ${SITE_NAME}` },
  description: SITE_DESCRIPTION,
  openGraph: { siteName: SITE_NAME, type: "website" },
  twitter: { card: "summary_large_image" },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col bg-zinc-100 font-sans text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
        <Header />
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">{children}</main>
        <footer className="mt-8 bg-indigo-950 text-sm text-indigo-100">
          <div className="mx-auto grid max-w-7xl gap-6 px-4 py-8 sm:grid-cols-3">
            <div>
              <p className="font-semibold text-white">Shop by category</p>
              <ul className="mt-2 space-y-1">
                {CATEGORIES.map((c) => <li key={c.id}><Link className="hover:underline" href={`/search?category=${c.id}`}>{c.name}</Link></li>)}
              </ul>
            </div>
            <div>
              <p className="font-semibold text-white">Your account</p>
              <ul className="mt-2 space-y-1">
                <li><Link className="hover:underline" href="/login">Sign in</Link></li>
                <li><Link className="hover:underline" href="/signup">Create an account</Link></li>
                <li><Link className="hover:underline" href="/orders">Your orders</Link></li>
                <li><Link className="hover:underline" href="/cart">Cart</Link></li>
              </ul>
            </div>
            <div>
              <p className="font-semibold text-white">About this store</p>
              <p className="mt-2 text-indigo-200">
                ShopSphere is a demonstration shop. Products, brands, prices and ratings are generated; checkout is simulated and
                takes no payment. It produces real traffic and logs for the SentinelOps AI reliability project.
              </p>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
