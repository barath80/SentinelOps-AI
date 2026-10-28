import { afterEach, vi } from "vitest";
import { memorySql, resetMemoryDb } from "@/lib/memoryDb";

// Tests run against the in-memory SQL stand-in (src/lib/memoryDb.ts), reset after each test.
export * from "@/lib/memoryDb";

vi.mock("@/lib/db", () => ({ db: () => memorySql }));

afterEach(resetMemoryDb);
