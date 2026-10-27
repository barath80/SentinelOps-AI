import { db } from "./db";
import type { Shipping } from "./orders";

export type Address = Shipping & { id: string; label: string; isDefault: boolean };

type Row = {
  id: string;
  label: string;
  full_name: string;
  line1: string;
  city: string;
  postal_code: string;
  country: string;
  is_default: boolean;
};

const toAddress = (r: Row): Address => ({
  id: r.id,
  label: r.label,
  fullName: r.full_name,
  line1: r.line1,
  city: r.city,
  postalCode: r.postal_code,
  country: r.country,
  isDefault: r.is_default,
});

export async function listAddresses(userId: string): Promise<Address[]> {
  const rows = (await db()`SELECT * FROM addresses WHERE user_id = ${userId} ORDER BY created_at`) as Row[];
  return rows.map(toAddress);
}

export async function addAddress(userId: string, label: string, shipping: Shipping): Promise<Address> {
  const rows = (await db()`
    INSERT INTO addresses (id, user_id, label, full_name, line1, city, postal_code, country)
    VALUES (${crypto.randomUUID()}, ${userId}, ${label}, ${shipping.fullName}, ${shipping.line1}, ${shipping.city}, ${shipping.postalCode}, ${shipping.country})
    RETURNING *`) as Row[];
  return toAddress(rows[0]);
}

export async function deleteAddress(userId: string, id: string): Promise<void> {
  await db()`DELETE FROM addresses WHERE id = ${id} AND user_id = ${userId}`;
}
