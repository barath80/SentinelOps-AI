import { describe, expect, it } from "vitest";
import { addAddress, deleteAddress, listAddresses } from "./addresses";

const shipping = { fullName: "Ada Lovelace", line1: "1 Analytical Engine Way", city: "London", postalCode: "AB1 2CD", country: "UK" };

describe("addresses", () => {
  it("adds and lists addresses for a user", async () => {
    await addAddress("u1", "Home", shipping);
    const addresses = await listAddresses("u1");
    expect(addresses).toHaveLength(1);
    expect(addresses[0]).toMatchObject({ label: "Home", fullName: "Ada Lovelace" });
  });

  it("deletes only the owner's address", async () => {
    const a = await addAddress("u1", "Home", shipping);
    await deleteAddress("u2", a.id); // not the owner: should not remove it
    expect(await listAddresses("u1")).toHaveLength(1);
    await deleteAddress("u1", a.id);
    expect(await listAddresses("u1")).toHaveLength(0);
  });

  it("keeps addresses separate per user", async () => {
    await addAddress("u1", "Home", shipping);
    await addAddress("u2", "Work", shipping);
    expect(await listAddresses("u1")).toHaveLength(1);
    expect(await listAddresses("u2")).toHaveLength(1);
  });
});
