import React from 'react';
import { cn } from '@/lib/utils';

// Typographic scale shared by both apps. Everything the interface says lands on
// one of four steps, so a screen never invents its own heading size:
//
//   Eyebrow      10px uppercase, wide tracking  — the "where am I" line
//   SectionTitle 15px semibold                  — a block of related content
//   body         14px (text-sm)                 — prose and controls
//   caption      12px muted (text-xs)           — hints under a control
//
// Anything larger than SectionTitle is a number, not a heading, and belongs to
// StatTile in metric.jsx.

export function Eyebrow({ icon: Icon = null, className = '', children, ...props }) {
  return (
    <p
      className={cn(
        'flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground',
        className
      )}
      {...props}
    >
      {Icon && <Icon className="h-3 w-3 shrink-0" aria-hidden="true" />}
      {children}
    </p>
  );
}

// A titled block. `action` sits on the baseline of the title on wide screens and
// wraps underneath on narrow ones.
export function Section({ eyebrow, icon, title, description, action, className = '', children }) {
  return (
    <section className={cn('space-y-3.5', className)}>
      {(eyebrow || title || action) && (
        <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
          <div className="min-w-0 space-y-1">
            {eyebrow && <Eyebrow icon={icon}>{eyebrow}</Eyebrow>}
            {title && (
              <h2 className="font-heading text-[15px] font-semibold leading-tight tracking-tight">
                {title}
              </h2>
            )}
            {description && (
              <p className="max-w-prose text-xs leading-relaxed text-muted-foreground">
                {description}
              </p>
            )}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

// Label for a form control. Matches the caption step so a field and its hint
// read as one unit.
export function FieldLabel({ className = '', children, ...props }) {
  return (
    <label
      className={cn('block text-xs font-medium text-muted-foreground', className)}
      {...props}
    >
      {children}
    </label>
  );
}

// Hairline divider used between stacked sections inside one scroll area.
export function Divider({ className = '' }) {
  return <hr className={cn('border-0 border-t border-border/70', className)} />;
}
