"use client";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import Link from "next/link";
import { useRouter } from "next/navigation";

export default function AccountMenu({ name }: { name: string }) {
  const router = useRouter();

  async function signOut() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/");
    router.refresh();
  }

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button type="button" className="leading-tight outline-none">
          <span className="block text-xs text-zinc-300">Hello, {name.split(" ")[0]}</span>
          <span className="text-sm font-semibold">Account &amp; Orders ▾</span>
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className="ui-animate-zoom z-30 flex w-44 flex-col gap-1 rounded-md bg-white p-2 text-zinc-900 shadow-lg"
        >
          <DropdownMenu.Item asChild>
            <Link href="/orders" className="cursor-pointer rounded px-2 py-1.5 text-sm outline-none hover:bg-zinc-100 focus:bg-zinc-100">
              Your orders
            </Link>
          </DropdownMenu.Item>
          <DropdownMenu.Item asChild>
            <Link href="/wishlist" className="cursor-pointer rounded px-2 py-1.5 text-sm outline-none hover:bg-zinc-100 focus:bg-zinc-100">
              Your wishlist
            </Link>
          </DropdownMenu.Item>
          <DropdownMenu.Item asChild>
            <Link href="/account" className="cursor-pointer rounded px-2 py-1.5 text-sm outline-none hover:bg-zinc-100 focus:bg-zinc-100">
              Account settings
            </Link>
          </DropdownMenu.Item>
          <DropdownMenu.Separator className="my-1 h-px bg-zinc-200" />
          <DropdownMenu.Item
            onSelect={signOut}
            className="cursor-pointer rounded px-2 py-1.5 text-sm outline-none hover:bg-zinc-100 focus:bg-zinc-100"
          >
            Sign out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
