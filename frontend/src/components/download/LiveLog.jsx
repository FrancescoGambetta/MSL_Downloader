import React, { useEffect, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Panel, PanelHeader, PanelBody } from '@/components/ui/panel';
import {
  Radio, Trash2, CheckCircle2, AlertTriangle, ArrowRightCircle, RefreshCw, SkipForward,
} from 'lucide-react';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { cn } from '@/lib/utils';

const TYPE_META = {
  download: { icon: RefreshCw, cls: 'text-primary' },
  convert: { icon: ArrowRightCircle, cls: 'text-amber-500' },
  skip: { icon: SkipForward, cls: 'text-muted-foreground' },
  error: { icon: AlertTriangle, cls: 'text-destructive' },
  success: { icon: CheckCircle2, cls: 'text-emerald-500' },
  info: { icon: Radio, cls: 'text-muted-foreground' },
};

export default function LiveLog({ log, progress, isRunning, onClear, className }) {
  const { t } = useAppSettings();
  const endRef = useRef(null);
  const pct = progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0;

  useEffect(() => {
    // `nearest` keeps the scroll inside the log instead of dragging the whole
    // page down every time a line is appended.
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [log]);

  return (
    <Panel className={cn('min-h-[17rem]', className)}>
      <PanelHeader>
        <div className="flex min-w-0 items-center gap-2">
          <span
            className={cn(
              'h-1.5 w-1.5 shrink-0 rounded-full',
              isRunning ? 'animate-pulse bg-emerald-500' : 'bg-muted-foreground/40'
            )}
            aria-hidden="true"
          />
          <h2 className="truncate font-heading text-[13px] font-semibold tracking-tight">
            {t('log.title')}
          </h2>
          {isRunning && (
            <span className="shrink-0 rounded bg-emerald-500/15 px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
              {t('log.live')}
            </span>
          )}
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0"
          onClick={onClear}
          disabled={log.length === 0}
          title={t('log.clear')}
          aria-label={t('log.clear')}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </PanelHeader>

      {(isRunning || pct > 0) && (
        <div className="shrink-0 border-b border-border px-4 py-2.5">
          <div className="mb-1.5 flex items-center justify-between text-[11px] text-muted-foreground">
            <span className="truncate">{t('execution.processing')}</span>
            <span className="shrink-0 font-mono tabular-nums">
              {progress.done}/{progress.total} · {pct}%
            </span>
          </div>
          <div
            className="h-1 overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className="h-full rounded-full bg-primary transition-[width] duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      )}

      <PanelBody scroll className="max-h-[20rem] space-y-0.5 px-2 py-2 font-mono text-[11px]">
        {log.length === 0 ? (
          <div className="flex h-full items-center justify-center py-6">
            <p className="text-center font-body text-xs text-muted-foreground">
              {t('log.empty')}
            </p>
          </div>
        ) : (
          log.map((entry) => {
            const meta = TYPE_META[entry.type] || TYPE_META.info;
            const Icon = meta.icon;
            return (
              <div
                key={entry.id}
                className="flex items-start gap-2 rounded-md px-2 py-1 transition-colors hover:bg-muted/60"
              >
                <Icon className={cn('mt-0.5 h-3.5 w-3.5 shrink-0', meta.cls)} aria-hidden="true" />
                <span className="shrink-0 tabular-nums text-muted-foreground/60">
                  {entry.ts.toLocaleTimeString()}
                </span>
                <span className={cn('min-w-0 break-words', entry.type === 'error' && 'text-destructive')}>
                  {entry.message}
                </span>
              </div>
            );
          })
        )}
        <div ref={endRef} />
      </PanelBody>
    </Panel>
  );
}
