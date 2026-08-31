import React, { useEffect, useRef } from 'react';
import { Radio, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Panel, PanelHeader, PanelBody } from '@/components/ui/panel';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { condenseLog, classifyLine } from '@/lib/rawJobLog';
import { cn } from '@/lib/utils';

// Shared "LIVE log" panel for any Catalog Manager job that tails a raw
// stdout log (catalog_manager/jobs.py) -- Updates and Personalize's
// customization runs both use it, so the panel/condense/classify logic
// lives in one place rather than being copy-pasted per tab.
export default function RawLiveLog({ logText, isLive, onClear, className }) {
  const { t } = useAppSettings();
  const endRef = useRef(null);

  useEffect(() => {
    // `nearest` keeps the scroll inside the log instead of dragging the
    // whole page down every time a line is appended.
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [logText]);

  return (
    <Panel className={cn('min-h-[17rem]', className)}>
      <PanelHeader>
        <div className="flex min-w-0 items-center gap-2">
          <span
            className={cn('h-1.5 w-1.5 shrink-0 rounded-full', isLive ? 'animate-pulse bg-emerald-500' : 'bg-muted-foreground/40')}
            aria-hidden="true"
          />
          <h2 className="truncate font-heading text-[13px] font-semibold tracking-tight">{t('log.title')}</h2>
          {isLive && (
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
          disabled={!logText}
          title={t('log.clear')}
          aria-label={t('log.clear')}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </PanelHeader>
      <PanelBody scroll className="max-h-[20rem] space-y-0.5 px-2 py-2 font-mono text-[11px]">
        {logText ? (
          condenseLog(logText).map((line, idx) => {
            const meta = classifyLine(line);
            const Icon = meta.icon;
            return (
              <div key={idx} className="flex items-start gap-2 rounded-md px-2 py-1 transition-colors hover:bg-muted/60">
                <Icon className={cn('mt-0.5 h-3.5 w-3.5 shrink-0', meta.cls)} aria-hidden="true" />
                <span className="min-w-0 break-words text-muted-foreground">{line}</span>
              </div>
            );
          })
        ) : (
          <div className="flex h-full items-center justify-center py-6">
            <p className="flex items-center gap-1.5 text-center font-body text-xs text-muted-foreground">
              <Radio className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              {t('log.empty')}
            </p>
          </div>
        )}
        <div ref={endRef} />
      </PanelBody>
    </Panel>
  );
}
