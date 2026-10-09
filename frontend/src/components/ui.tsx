import type { ReactNode } from "react";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

/* ------------------------------------------------------------------ panels */

export function Panel({
  children,
  className,
  as: Tag = "section",
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article" | "aside";
}) {
  return <Tag className={cx("panel", className)}>{children}</Tag>;
}

export function PanelHeader({
  title,
  subtitle,
  actions,
  icon,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <header className="panel-header">
      <div className="flex min-w-0 items-center gap-2.5">
        {icon ? <span className="text-stone-500">{icon}</span> : null}
        <div className="min-w-0">
          <h2 className="panel-title truncate">{title}</h2>
          {subtitle ? <p className="mt-0.5 truncate text-xs text-stone-500">{subtitle}</p> : null}
        </div>
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-1.5">{actions}</div> : null}
    </header>
  );
}

/* ----------------------------------------------------------------- buttons */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

export function Button({
  children,
  variant = "secondary",
  className,
  icon,
  ...rest
}: {
  children?: ReactNode;
  variant?: ButtonVariant;
  className?: string;
  icon?: ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const variantClass =
    variant === "primary"
      ? "btn-primary"
      : variant === "ghost"
        ? "btn-ghost"
        : variant === "danger"
          ? "btn-danger"
          : "btn-secondary";
  return (
    <button type="button" className={cx(variantClass, className)} {...rest}>
      {icon}
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------- chips */

export function StatusChip({ status, label }: { status: string; label?: string }) {
  const tone: Record<string, string> = {
    succeeded: "text-forest-700 border-forest-300 bg-forest-50",
    done: "text-forest-700 border-forest-300 bg-forest-50",
    running: "text-signal-blue border-signal-blue/30 bg-signal-blue/10",
    queued: "text-stone-600 border-stone-300 bg-stone-100",
    pending: "text-stone-500 border-stone-300 bg-stone-100",
    skipped: "text-signal-amber border-signal-amber/30 bg-signal-amber/10",
    failed: "text-signal-red border-signal-red/30 bg-signal-red/10",
  };
  const dot: Record<string, string> = {
    succeeded: "bg-forest-500",
    done: "bg-forest-500",
    running: "bg-signal-blue animate-pulse",
    queued: "bg-stone-400",
    pending: "bg-stone-400",
    skipped: "bg-signal-amber",
    failed: "bg-signal-red",
  };
  return (
    <span className={cx("chip", tone[status] ?? tone.pending)}>
      <span className={cx("h-1.5 w-1.5 rounded-full", dot[status] ?? dot.pending)} />
      {label ?? status}
    </span>
  );
}

export function Chip({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: "neutral" | "green" | "amber" | "red" | "blue";
  title?: string;
}) {
  const tones: Record<string, string> = {
    neutral: "text-stone-600 border-stone-300 bg-stone-100",
    green: "text-forest-700 border-forest-300 bg-forest-50",
    amber: "text-signal-amber border-signal-amber/30 bg-signal-amber/10",
    red: "text-signal-red border-signal-red/30 bg-signal-red/10",
    blue: "text-signal-blue border-signal-blue/30 bg-signal-blue/10",
  };
  return (
    <span className={cx("chip", tones[tone])} title={title}>
      {children}
    </span>
  );
}

/* -------------------------------------------------------------- measurements */

/** A single measured value. `value === null` renders as an explicit "not measured". */
export function Stat({
  label,
  value,
  hint,
  tone = "default",
  unavailableReason,
  mono = true,
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "warn" | "good";
  unavailableReason?: string;
  mono?: boolean;
  icon?: ReactNode;
}) {
  const missing = value === null || value === undefined || value === "";
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1 text-2xs font-semibold uppercase tracking-[0.07em] text-stone-500">
        {icon ? <span className="text-stone-400">{icon}</span> : null}
        {label}
      </div>
      <div
        className={cx(
          "mt-0.5 truncate text-[15px] leading-6",
          mono && "tnum",
          missing
            ? "text-stone-400 italic"
            : tone === "warn"
              ? "text-signal-amber"
              : tone === "good"
                ? "text-forest-700"
                : "text-stone-900",
        )}
        title={missing && unavailableReason ? unavailableReason : undefined}
      >
        {missing ? "not measured" : value}
      </div>
      {hint ? <div className="mt-0.5 truncate text-2xs text-stone-500">{hint}</div> : null}
    </div>
  );
}

export function KeyValue({
  label,
  value,
  mono = true,
  title,
}: {
  label: ReactNode;
  value: ReactNode;
  mono?: boolean;
  title?: string;
}) {
  const missing = value === null || value === undefined || value === "";
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-stone-200 py-1.5 last:border-b-0">
      <dt className="shrink-0 text-xs text-stone-500">{label}</dt>
      <dd
        className={cx(
          "min-w-0 truncate text-right text-xs",
          mono && "tnum",
          missing ? "text-stone-400 italic" : "text-stone-800",
        )}
        title={title}
      >
        {missing ? "not measured" : value}
      </dd>
    </div>
  );
}

/* ---------------------------------------------------------------- feedback */

export function Callout({
  tone = "info",
  title,
  children,
  icon,
  action,
}: {
  tone?: "info" | "warn" | "danger" | "good";
  title?: ReactNode;
  children?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  const tones = {
    info: "border-stone-300 bg-stone-50 text-stone-700",
    warn: "border-signal-amber/40 bg-signal-amber/[0.07] text-stone-800",
    danger: "border-signal-red/40 bg-signal-red/[0.06] text-stone-800",
    good: "border-forest-300 bg-forest-50 text-stone-800",
  } as const;
  const icons = {
    info: "text-stone-500",
    warn: "text-signal-amber",
    danger: "text-signal-red",
    good: "text-forest-600",
  } as const;
  return (
    <div className={cx("flex items-start gap-2.5 rounded-card border px-3 py-2.5 text-xs", tones[tone])}>
      {icon ? <span className={cx("mt-px shrink-0", icons[tone])}>{icon}</span> : null}
      <div className="min-w-0 flex-1">
        {title ? <div className="font-semibold">{title}</div> : null}
        {children ? <div className={cx(Boolean(title) && "mt-0.5", "leading-relaxed text-stone-600")}>{children}</div> : null}
      </div>
      {action}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  children,
  action,
}: {
  icon?: ReactNode;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      {icon ? (
        <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-full border border-stone-300 bg-stone-100 text-stone-500">
          {icon}
        </div>
      ) : null}
      <h3 className="text-sm font-semibold text-stone-800">{title}</h3>
      {children ? <div className="mt-1.5 max-w-md text-xs leading-relaxed text-stone-500">{children}</div> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cx(
        "inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-stone-300 border-t-forest-600",
        className,
      )}
      role="status"
      aria-label="loading"
    />
  );
}

export function SkeletonRows({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div className={cx("space-y-2 p-4", className)} aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-3 animate-pulse rounded bg-stone-200" style={{ width: `${92 - i * 11}%` }} />
      ))}
    </div>
  );
}

export function ProgressBar({
  value,
  max = 100,
  indeterminate,
  tone = "forest",
}: {
  value?: number | null;
  max?: number;
  indeterminate?: boolean;
  tone?: "forest" | "amber" | "red";
}) {
  const pct = indeterminate ? 100 : Math.max(0, Math.min(100, ((value ?? 0) / max) * 100));
  const bar = { forest: "bg-forest-600", amber: "bg-signal-amber", red: "bg-signal-red" }[tone];
  return (
    <div
      className="h-1 w-full overflow-hidden rounded-full bg-stone-200"
      role="progressbar"
      aria-valuenow={indeterminate ? undefined : Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={cx("h-full rounded-full transition-[width] duration-200", bar, indeterminate && "animate-pulse")}
        style={{ width: indeterminate ? "100%" : `${pct}%` }}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ inputs */

export function Field({
  label,
  hint,
  error,
  children,
  required,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  required?: boolean;
}) {
  return (
    <label className="block">
      <span className="label">
        {label}
        {required ? <span className="ml-0.5 text-signal-red">*</span> : null}
      </span>
      {children}
      {error ? (
        <span className="mt-1 block text-2xs text-signal-red">{error}</span>
      ) : hint ? (
        <span className="mt-1 block text-2xs leading-relaxed text-stone-500">{hint}</span>
      ) : null}
    </label>
  );
}

export function Select({
  value,
  onChange,
  options,
  className,
  disabled,
  id,
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string; disabled?: boolean }[];
  className?: string;
  disabled?: boolean;
  id?: string;
}) {
  return (
    <select
      id={id}
      className={cx("field", className)}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value} disabled={o.disabled}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5">
      <div className="min-w-0">
        <div className="text-sm text-stone-800">{label}</div>
        {hint ? <div className="mt-0.5 text-2xs leading-relaxed text-stone-500">{hint}</div> : null}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={typeof label === "string" ? label : "toggle"}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cx(
          "relative mt-0.5 h-5 w-9 shrink-0 rounded-full border transition-colors",
          checked ? "border-forest-700 bg-forest-600" : "border-stone-300 bg-stone-200",
          disabled && "opacity-50",
        )}
      >
        <span
          className={cx(
            "absolute top-0.5 h-3.5 w-3.5 rounded-full bg-stone-50 shadow-sm transition-all",
            checked ? "left-[1.15rem]" : "left-0.5",
          )}
        />
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------- table */

export function DataTable<T>({
  rows,
  columns,
  getRowKey,
  empty,
  compact,
}: {
  rows: T[];
  columns: {
    key: string;
    header: ReactNode;
    render: (row: T) => ReactNode;
    className?: string;
    align?: "left" | "right" | "center";
  }[];
  getRowKey: (row: T, index: number) => string;
  empty?: ReactNode;
  compact?: boolean;
}) {
  if (!rows.length) return <>{empty ?? null}</>;
  return (
    <div className="scroll-thin overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="border-b border-stone-300 text-left">
            {columns.map((c) => (
              <th
                key={c.key}
                className={cx(
                  "whitespace-nowrap px-3 font-semibold uppercase tracking-[0.06em] text-2xs text-stone-500",
                  compact ? "py-1.5" : "py-2",
                  c.align === "right" && "text-right",
                  c.align === "center" && "text-center",
                  c.className,
                )}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={getRowKey(row, i)} className="border-b border-stone-200 last:border-b-0 hover:bg-stone-100/70">
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={cx(
                    "px-3 align-top text-stone-700",
                    compact ? "py-1.5" : "py-2",
                    c.align === "right" && "text-right tnum",
                    c.align === "center" && "text-center",
                    c.className,
                  )}
                >
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Tooltip({ text, children }: { text: string; children: ReactNode }) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-2 w-max max-w-[17rem]
          -translate-x-1/2 rounded-[4px] border border-stone-700 bg-stone-900 px-2 py-1.5
          text-2xs font-normal leading-relaxed text-stone-100 opacity-0 shadow-raised
          transition-opacity duration-100 group-hover:opacity-100 group-focus-visible:opacity-100"
      >
        {text}
      </span>
    </span>
  );
}

/** Small inline "(?)" affordance used next to measurements whose meaning matters. */
export function Hint({ text }: { text: string }) {
  return (
    <Tooltip text={text}>
      <span
        tabIndex={0}
        className="ml-1 inline-flex h-3.5 w-3.5 cursor-help items-center justify-center rounded-full
          border border-stone-300 text-[9px] font-semibold text-stone-500 hover:border-stone-400"
      >
        ?
      </span>
    </Tooltip>
  );
}
