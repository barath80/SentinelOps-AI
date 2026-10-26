// Runs once when the server starts. Network tuning for hosts with slow or broken IPv6:
// Node's connection fallback gives each address only 250 ms, so a healthy ~270 ms IPv4
// connect to Neon was cancelled over and over until a 10 s timeout. Prefer IPv4 and allow
// each address 2 s. Harmless on Vercel.
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const dns = await import("node:dns");
    const net = await import("node:net");
    dns.setDefaultResultOrder("ipv4first");
    net.setDefaultAutoSelectFamilyAttemptTimeout(2000);
  }
}
