import React from 'react';
import { createPortal } from 'react-dom';
import { Button } from '@/components/ui/button';
import { X } from 'lucide-react';
import { useDismissable } from '@/hooks/use-dismissable';
import { cn } from '@/lib/utils';

// Both dialogs used to hand-roll their own overlay, which meant neither closed
// on Escape nor stopped the page behind them from scrolling. Rendering in a
// portal also keeps them from being clipped by the app shell.

export function Modal({ open, onClose, title, icon: Icon = null, size = 'md', children, footer = null }) {
  useDismissable(open, onClose);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          'relative flex max-h-[92svh] w-full flex-col overflow-hidden border border-border bg-card shadow-2xl',
          'rounded-t-3xl sm:rounded-2xl',
          'animate-in duration-200 slide-in-from-bottom-4 sm:zoom-in-95 sm:slide-in-from-bottom-0',
          size === 'lg' ? 'sm:max-w-lg' : 'sm:max-w-md'
        )}
      >
        <div className="flex shrink-0 items-start justify-between gap-3 px-5 pb-4 pt-5 sm:px-6">
          <div className="flex min-w-0 items-center gap-2.5">
            {Icon && <Icon className="h-5 w-5 shrink-0 text-primary" aria-hidden="true" />}
            <h2 className="font-heading text-lg font-semibold tracking-tight">{title}</h2>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="-mr-1.5 h-8 w-8 shrink-0"
            onClick={onClose}
            aria-label={title}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-5 sm:px-6">
          {children}
        </div>

        {footer && (
          <div className="flex shrink-0 justify-end gap-2 border-t border-border px-5 py-4 sm:px-6">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}

// Side sheet used for settings: full width on phones, a panel on the right
// from `sm` up. Same dismiss rules as Modal.
export function Sheet({ open, onClose, title, icon: Icon = null, children }) {
  useDismissable(open, onClose);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          'relative flex h-full w-full flex-col border-l border-border bg-card shadow-2xl',
          'sm:max-w-xl',
          'animate-in duration-300 slide-in-from-right'
        )}
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-5 py-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-2.5">
            {Icon && <Icon className="h-5 w-5 shrink-0 text-primary" aria-hidden="true" />}
            <h2 className="font-heading text-lg font-semibold tracking-tight">{title}</h2>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="-mr-1.5 h-8 w-8 shrink-0"
            onClick={onClose}
            aria-label={title}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-6 sm:px-6">
          {children}
        </div>
      </div>
    </div>,
    document.body
  );
}
