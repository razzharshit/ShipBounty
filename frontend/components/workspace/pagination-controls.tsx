import Link from "next/link";
import { ArrowLeft, ArrowRight } from "lucide-react";

type PaginationControlsProps = {
  pathname: string;
  total: number;
  limit: number;
  offset: number;
  hasMore: boolean;
  offsetKey?: string;
  query?: Record<string, string | number | undefined>;
};

export function PaginationControls({
  pathname,
  total,
  limit,
  offset,
  hasMore,
  offsetKey = "offset",
  query = {},
}: PaginationControlsProps) {
  if (total <= limit && offset === 0) return null;

  const hrefFor = (nextOffset: number) => {
    const parameters = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== "") {
        parameters.set(key, String(value));
      }
    });
    if (nextOffset > 0) parameters.set(offsetKey, String(nextOffset));
    else parameters.delete(offsetKey);
    const encoded = parameters.toString();
    return encoded ? `${pathname}?${encoded}` : pathname;
  };
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + limit, total);
  const previousOffset = Math.max(0, offset - limit);

  return (
    <nav
      data-testid="pagination-controls"
      aria-label="Collection pagination"
      className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-4"
    >
      <p className="text-sm text-muted-foreground">
        Records {start}–{end} of {total}
      </p>
      <div className="flex gap-2">
        {offset > 0 ? (
          <Link
            href={hrefFor(previousOffset)}
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-border bg-card px-3 text-sm font-semibold hover:bg-accent"
          >
            <ArrowLeft className="h-4 w-4" />
            Previous
          </Link>
        ) : (
          <span
            aria-disabled="true"
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-border px-3 text-sm font-semibold opacity-40"
          >
            <ArrowLeft className="h-4 w-4" />
            Previous
          </span>
        )}
        {hasMore ? (
          <Link
            href={hrefFor(offset + limit)}
            className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-3 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
          >
            Next
            <ArrowRight className="h-4 w-4" />
          </Link>
        ) : (
          <span
            aria-disabled="true"
            className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-3 text-sm font-semibold text-primary-foreground opacity-40"
          >
            Next
            <ArrowRight className="h-4 w-4" />
          </span>
        )}
      </div>
    </nav>
  );
}
