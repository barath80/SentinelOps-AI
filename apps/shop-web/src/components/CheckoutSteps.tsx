const STEPS = ["Cart", "Shipping", "Payment", "Review"];

export default function CheckoutSteps({ current }: { current: number }) {
  return (
    <ol className="flex items-center gap-2 text-sm" aria-label="Checkout progress">
      {STEPS.map((step, i) => (
        <li key={step} className="flex items-center gap-2">
          <span
            className={`flex items-center gap-1.5 ${i <= current ? "font-semibold text-indigo-700 dark:text-indigo-300" : "text-zinc-400"}`}
            aria-current={i === current ? "step" : undefined}
          >
            <span
              className={`flex h-5 w-5 items-center justify-center rounded-full text-xs ${
                i < current
                  ? "bg-indigo-600 text-white"
                  : i === current
                    ? "border-2 border-indigo-600 text-indigo-700 dark:text-indigo-300"
                    : "border border-zinc-300 dark:border-zinc-700"
              }`}
            >
              {i < current ? "✓" : i + 1}
            </span>
            {step}
          </span>
          {i < STEPS.length - 1 && <span className="h-px w-6 bg-zinc-300 dark:bg-zinc-700" aria-hidden="true" />}
        </li>
      ))}
    </ol>
  );
}
