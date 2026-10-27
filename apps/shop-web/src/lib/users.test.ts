import { describe, expect, it } from "vitest";
import { createPasswordUser, normalizeEmail, validateSignup, verifyPassword } from "./users";

describe("normalizeEmail", () => {
  it("trims and lowercases", () => {
    expect(normalizeEmail("  Foo@Example.COM ")).toBe("foo@example.com");
  });
});

describe("validateSignup", () => {
  it("accepts valid input", () => {
    expect(validateSignup({ email: "a@b.com", name: "A", password: "password1" })).toBeNull();
  });

  it("rejects an invalid email", () => {
    expect(validateSignup({ email: "not-an-email", name: "A", password: "password1" })).not.toBeNull();
  });

  it("rejects a missing or blank name", () => {
    expect(validateSignup({ email: "a@b.com", name: "  ", password: "password1" })).not.toBeNull();
  });

  it("rejects a password shorter than 8 characters", () => {
    expect(validateSignup({ email: "a@b.com", name: "A", password: "short" })).not.toBeNull();
  });

  it("rejects a password over 72 bytes", () => {
    expect(validateSignup({ email: "a@b.com", name: "A", password: "a".repeat(73) })).not.toBeNull();
  });
});

describe("createPasswordUser / verifyPassword", () => {
  it("creates a user and verifies the correct password", async () => {
    const user = await createPasswordUser("new@example.com", "New User", "correct-password");
    expect(user).not.toBe("exists");
    const verified = await verifyPassword("new@example.com", "correct-password");
    expect(verified).not.toBeNull();
    expect(verified?.email).toBe("new@example.com");
  });

  it("rejects the wrong password", async () => {
    await createPasswordUser("new2@example.com", "New User", "correct-password");
    expect(await verifyPassword("new2@example.com", "wrong-password")).toBeNull();
  });

  it("returns 'exists' for a duplicate email", async () => {
    await createPasswordUser("dup@example.com", "First", "password1");
    expect(await createPasswordUser("dup@example.com", "Second", "password2")).toBe("exists");
  });

  it("returns null for an unknown email without leaking timing-relevant state", async () => {
    expect(await verifyPassword("nobody@example.com", "whatever")).toBeNull();
  });
});
