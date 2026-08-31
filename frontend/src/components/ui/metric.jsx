import React from 'react';
import { cn } from '@/lib/utils';

// Numbers are the only thing in the interface allowed to be large, and they are
// always monospaced + tabular so a column of them lines up.

const TONES = {
  default: 'text-foreground',
  muted: 'text-muted-foreground',
  accent: 'text-primary',
  positive: 'text-emerald-600 dark:text-emerald-400',
  warning: 'text-amber-600 dark:text-amber-400',
};

// A single figure with its label above and an optional qualifier below.
// `dot` renders a status pill instead of a figure, for non-numeric states.
export function StatTile({ label, value, hint, tone = 'default', dot = false, className = '' }) {
  return (
    <div className={cn('rounded-lg border border-border bg-card px-3.5 py-3', className)}>
      <p className="truncate text-[10px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </p>
      <p
        className={cn(
          'mt-1.5 flex items-center gap-1.5 truncate',
          dot
            ? 'text-[13px] font-medium leading-tight'
            : 'font-mono text-xl font-semibold leading-none tabular-nums',
          TONES[tone] || TONES.default
        )}
      >
        {dot && (
          <span
            className={cn(
              'h-1.5 w-1.5 shrink-0 rounded-full',
              tone === 'warning' ? 'bg-amber-500' : tone === 'positive' ? 'bg-emerald-500' : 'bg-current'
            )}
            aria-hidden="true"
          />
        )}
        <span className="truncate">{value}</span>
      </p>
      {hint && <p className="mt-1 truncate text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

// Horizontal bar with the label and figure on one line above it. Used for the
// per-camera breakdown and for the install progress.
export function Meter({ label, value, max = 100, display, tone = 'accent', className = '' }) {
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return (
    <div className={cn('space-y-1.5', className)}>
      <div className="flex items-baseline justify-between gap-3">
        <span className="truncate text-xs font-medium">{label}</span>
        <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
          {display ?? value.toLocaleString()}
        </span>
      </div>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
      >
        <div
          className={cn(
            'h-full rounded-full transition-[width] duration-300 ease-out',
            tone === 'positive' ? 'bg-emerald-500' : 'bg-primary'
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// Label/value pair. Stacked in a `divide-y` list they read as a spec sheet.
export function DataRow({ icon: Icon, label, value, mono = true, className = '' }) {
  return (
    <div className={cn('flex items-center justify-between gap-3 py-2', className)}>
      <span className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
        {Icon && <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />}
        <span className="truncate">{label}</span>
      </span>
      <span
        className={cn(
          'max-w-[58%] truncate text-right text-xs font-medium',
          mono && 'font-mono tabular-nums'
        )}
      >
        {value}
      </span>
    </div>
  );
}
