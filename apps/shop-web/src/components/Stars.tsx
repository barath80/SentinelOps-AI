import { formatCount } from "@/lib/products";

// Five stars filled to the exact rating (e.g. 4.3 fills 4 stars and 30% of the fifth).
export default function Stars({ rating, count, size = 16 }: { rating: number; count?: number; size?: number }) {
  return (
    <span className="inline-flex items-center gap-1" title={`${rating} out of 5`}>
      <span className="inline-flex" aria-label={`${rating} out of 5 stars`}>
        {Array.from({ length: 5 }, (_, i) => {
          const fill = Math.max(0, Math.min(1, rating - i));
          return (
            <svg key={i} width={size} height={size} viewBox="0 0 20 20" aria-hidden="true">
              <defs>
                <linearGradient id={`s${i}-${Math.round(fill * 100)}`}>
                  <stop offset={`${fill * 100}%`} stopColor="#f59e0b" />
                  <stop offset={`${fill * 100}%`} stopColor="#d1d5db" />
                </linearGradient>
              </defs>
              <path d="M10 1.5l2.6 5.5 6 .7-4.5 4.1 1.2 5.9L10 14.8 4.7 17.7l1.2-5.9L1.4 7.7l6-.7z" fill={`url(#s${i}-${Math.round(fill * 100)})`} />
            </svg>
          );
        })}
      </span>
      <span className="text-sm text-amber-700 dark:text-amber-400">{rating.toFixed(1)}</span>
      {count !== undefined && <span className="text-sm text-sky-700 dark:text-sky-400">({formatCount(count)})</span>}
    </span>
  );
}
