import React, { useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Loader2 } from 'lucide-react';
import { explainSegment } from '@/lib/catalogManagerApi';
import { cn } from '@/lib/utils';

// Shared by CatalogComposition.jsx and CatalogPersonalize.jsx -- both show
// the same raw NASA filename-segment codes (product_type, suffix,
// camera_prefix, processing_marker, ...), so both explain them the same way.
//
// Rendered via a portal into document.body rather than positioned inline:
// codes usually sit inside a Panel, which clips overflow (see
// components/ui/panel.jsx) -- an inline-positioned tooltip on a row near the
// panel's edge would get cut off. Fetches segment_explain.py's explanation
// lazily on first hover/focus (explainSegment() caches it after that, so
// re-hovering repaints instantly), and flips above the code instead of below
// when there isn't room underneath.
export default function CodeTooltip({ dimension, code, lang, camera = '', className }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  const [coords, setCoords] = useState(null);
  const triggerRef = useRef(null);

  const show = () => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect) {
      const openAbove = rect.top > window.innerHeight / 2;
      setCoords({
        left: Math.max(8, Math.min(rect.left, window.innerWidth - 272)),
        ...(openAbove ? { bottom: window.innerHeight - rect.top + 6 } : { top: rect.bottom + 6 }),
      });
    }
    setOpen(true);
    if (!detail) explainSegment(dimension, code, lang, camera).then(setDetail).catch(() => {});
  };
  const hide = () => setOpen(false);

  return (
    <>
      <span
        ref={triggerRef}
        tabIndex={0}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        className={cn(
          'cursor-help rounded font-mono font-semibold text-primary outline-none transition-colors hover:bg-primary/10 focus-visible:ring-1 focus-visible:ring-ring',
          className
        )}
      >
        {code}
      </span>
      {open &&
        coords &&
        createPortal(
          <div
            role="tooltip"
            style={{ position: 'fixed', left: coords.left, top: coords.top, bottom: coords.bottom }}
            className="z-50 w-64 whitespace-pre-line rounded-md border border-border bg-popover p-2.5 text-[11px] leading-relaxed text-popover-foreground shadow-lg"
          >
            {detail ? (
              <>
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{detail.role}</p>
                {detail.explanation}
              </>
            ) : (
              <Loader2 className="h-3 w-3 animate-spin" />
            )}
          </div>,
          document.body
        )}
    </>
  );
}
