import { describe, expect, it } from "vitest";
import { consumeResetToken, createResetToken } from "./passwordReset";
import { createPasswordUser, verifyPassword } from "./users";

describe("createResetToken / consumeResetToken", () => {
  it("returns null for an unknown email", async () => {
    expect(await createResetToken("nobody@example.com")).toBeNull();
  });

  it("issues a token that resets the password exactly once", async () => {
    await createPasswordUser("reset@example.com", "Resetter", "old-password");
    const token = await createResetToken("reset@example.com");
    expect(token).not.toBeNull();

    expect(await consumeResetToken(token!, "new-password-1")).toBe(true);
    expect(await verifyPassword("reset@example.com", "new-password-1")).not.toBeNull();
    expect(await verifyPassword("reset@example.com", "old-password")).toBeNull();

    // Reusing the same token a second time must fail (single use).
    expect(await consumeResetToken(token!, "new-password-2")).toBe(false);
  });

  it("rejects an unknown or malformed token", async () => {
    expect(await consumeResetToken("not-a-real-token", "whatever-password")).toBe(false);
  });
});
