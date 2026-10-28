import { afterEach, describe, expect, it, vi } from "vitest";

// The setup file mocks ./db for every other test; this one checks the real module.
vi.unmock("@/lib/db");

afterEach(() => vi.unstubAllEnvs());

describe("db() store selection", () => {
  it("uses the in-memory store for local runs with SHOP_DB=memory", async () => {
    vi.stubEnv("SHOP_DB", "memory");
    vi.stubEnv("VERCEL", "");
    const { db } = await import("./db");
    const { memorySql } = await import("./memoryDb");
    expect(db()).toBe(memorySql);
  });

  it("refuses the in-memory store on a Vercel deployment", async () => {
    vi.stubEnv("SHOP_DB", "memory");
    vi.stubEnv("VERCEL", "1");
    const { db } = await import("./db");
    expect(() => db()).toThrow("local runs only");
  });

  it("fails closed without a database URL", async () => {
    vi.stubEnv("SHOP_DB", "");
    vi.stubEnv("DATABASE_URL", "");
    const { db } = await import("./db");
    expect(() => db()).toThrow("DATABASE_URL is not set");
  });
});
