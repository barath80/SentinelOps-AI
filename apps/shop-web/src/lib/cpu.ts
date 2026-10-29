// Per-request CPU time. process.cpuUsage() is process-wide, so a reading is only this request's own
// CPU time when no other request ran on the process at the same time: the usual case on a
// serverless instance. When requests overlap, nothing is recorded rather than a misleading number
// (SentinelOps' CPU diagnostic and its learned model would otherwise blame CPU for a neighbour's work).

let inFlight = 0;
let started = 0;

export type CpuTimer = { usage: NodeJS.CpuUsage; startedBefore: number; alone: boolean; done: boolean };

export function beginCpu(): CpuTimer {
  const timer = { usage: process.cpuUsage(), startedBefore: started, alone: inFlight === 0, done: false };
  inFlight += 1;
  started += 1;
  return timer;
}

// Milliseconds of CPU used by this request alone, or undefined when another request overlapped it.
// Safe to call more than once: only the first call counts.
export function endCpu(timer: CpuTimer): number | undefined {
  if (timer.done) return undefined;
  timer.done = true;
  inFlight -= 1;
  const exclusive = timer.alone && started === timer.startedBefore + 1;
  if (!exclusive) return undefined;
  const used = process.cpuUsage(timer.usage);
  return Math.round((used.user + used.system) / 1000);
}
