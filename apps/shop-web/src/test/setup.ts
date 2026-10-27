import { afterEach, vi } from "vitest";

// In-memory stand-in for the request-scoped cookie jar `next/headers` normally provides.
export const cookieStore = new Map<string, { value: string }>();

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => cookieStore.get(name),
    set: (name: string, value: string) => {
      cookieStore.set(name, { value });
    },
    delete: (name: string) => {
      cookieStore.delete(name);
    },
  }),
}));

// `after()` only works inside a real Next request; run the callback inline for tests.
vi.mock("next/server", () => ({
  after: (cb: () => unknown) => {
    void cb();
  },
}));

afterEach(() => {
  cookieStore.clear();
});
