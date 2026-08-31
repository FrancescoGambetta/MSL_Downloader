import React from 'react';
import { cn } from '@/lib/utils';

// Small pill-shaped on/off control used for camera, catalog, language and
// theme selection. It lives under its own name because `toggle` is taken by
// the shadcn primitive naming scheme this project follows.

export default function ToggleChip({ active, onClick, children, className = '', ...props }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'inline-flex items-center justify-center gap-1.5 rounded-full border px-3.5 py-2',
        'text-sm font-medium transition-all duration-150',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
        active
          ? 'border-primary bg-primary text-primary-foreground shadow-sm'
          : 'border-border bg-background/60 text-foreground hover:border-primary/40 hover:bg-accent/60',
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}
