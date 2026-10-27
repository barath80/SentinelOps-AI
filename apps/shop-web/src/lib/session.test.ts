import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { authConfigured, createSession, getSession, safeNext } from "./session";

const ORIGINAL_SECRET = process.env.AUTH_SECRET;

beforeEach(() => {
  process.env.AUTH_SECRET = "a".repeat(32);
});

afterEach(() => {
  process.env.AUTH_SECRET = ORIGINAL_SECRET;
});

describe("authConfigured", () => {
  it("requires at least 32 characters", () => {
    process.env.AUTH_SECRET = "too-short";
    expect(authConfigured()).toBe(false);
    process.env.AUTH_SECRET = "a".repeat(32);
    expect(authConfigured()).toBe(true);
  });
});

describe("createSession / getSession", () => {
  it("round-trips a valid session", async () => {
    await createSession({ userId: "u1", name: "Ada", email: "ada@example.com" });
    const session = await getSession();
    expect(session).toEqual({ userId: "u1", name: "Ada", email: "ada@example.com" });
  });

  it("returns null when AUTH_SECRET is not configured", async () => {
    await createSession({ userId: "u1", name: "Ada", email: "ada@example.com" });
    process.env.AUTH_SECRET = "too-short";
    expect(await getSession()).toBeNull();
  });

  it("returns null for a tampered cookie", async () => {
    const { cookieStore } = await import("../test/setup");
    await createSession({ userId: "u1", name: "Ada", email: "ada@example.com" });
    const cookie = cookieStore.get("session")!;
    cookieStore.set("session", { value: cookie.value.slice(0, -2) + "xx" });
    expect(await getSession()).toBeNull();
  });
});

describe("safeNext", () => {
  it("allows relative paths", () => {
    expect(safeNext("/account")).toBe("/account");
  });

  it("falls back to / for protocol-relative URLs", () => {
    expect(safeNext("//evil.com")).toBe("/");
  });

  it("falls back to / for backslash-based open redirects", () => {
    expect(safeNext("/\\evil.com")).toBe("/");
  });

  it("falls back to / for missing or absolute values", () => {
    expect(safeNext(null)).toBe("/");
    expect(safeNext(undefined)).toBe("/");
    expect(safeNext("https://evil.com")).toBe("/");
  });
});
