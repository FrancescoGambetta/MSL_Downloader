import React from 'react';
import { cn } from '@/lib/utils';

// Every surface in both apps (filters, log, gallery, viewport, metadata,
// catalog cards) is the same card: hairline border, a header strip, a body and
// an optional footer. Panel keeps that shape in one place so the pages only
// describe what goes inside.
//
// The card is deliberately quiet: `rounded-lg` matches the controls sitting
// inside it, and the elevation is static — a panel is furniture, not a button,
// so it must not react to the cursor.

export function Panel({ className = '', children, ...props }) {
  return (
    <div
      className={cn(
        'flex flex-col overflow-hidden rounded-lg border border-border bg-card',
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function PanelHeader({ className = '', children, ...props }) {
  return (
    <div
      className={cn(
        'flex h-11 shrink-0 items-center justify-between gap-3 border-b border-border px-4',
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function PanelTitle({ icon: Icon = null, children, className = '', ...props }) {
  return (
    <div className={cn('flex min-w-0 items-center gap-2', className)} {...props}>
      {Icon && <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />}
      <h2 className="truncate font-heading text-[13px] font-semibold tracking-tight">{children}</h2>
    </div>
  );
}

export function PanelBody({ className = '', scroll = false, children, ...props }) {
  return (
    <div
      className={cn('min-h-0 flex-1 px-4 py-3.5', scroll && 'overflow-y-auto', className)}
      {...props}
    >
      {children}
    </div>
  );
}

export function PanelFooter({ className = '', children, ...props }) {
  return (
    <div
      className={cn('shrink-0 border-t border-border px-4 py-3', className)}
      {...props}
    >
      {children}
    </div>
  );
}

// Shared "nothing here yet" state — used by the gallery, the viewport, the
// metadata panel and the log.
export function PanelEmpty({ icon: Icon = null, children }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2.5 py-8 text-center">
      {Icon && <Icon className="h-7 w-7 text-muted-foreground/25" aria-hidden="true" />}
      <p className="max-w-[26ch] text-xs leading-relaxed text-muted-foreground">{children}</p>
    </div>
  );
}
