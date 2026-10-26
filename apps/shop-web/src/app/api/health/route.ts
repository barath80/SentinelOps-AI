import { instrument } from "@/lib/handler";

export const GET = instrument("/api/health", async () => Response.json({ status: "ok" }));
