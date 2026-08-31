import React from 'react';
import { Button } from '@/components/ui/button';
import { SlidersHorizontal } from 'lucide-react';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { cn } from '@/lib/utils';

// The header already names the app and what it does, so repeating that as a
// hero cost ~110px of every screen for no information. This is the same block
// reduced to what actually changes while you work: the two counters, whether a
// run is live, and the filter drawer on small screens.

function Stat({ value, label }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="font-mono text-sm font-semibold tabular-nums">{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

export default function PageIntro({ foundCount, isRunning, onOpenFilters }) {
  const { t } = useAppSettings();

  return (
    <div className="flex flex-wrap items-center justify-between gap-x-5 gap-y-2.5 border-b border-border/70 pb-4">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-primary">
          {t('intro.eyebrow')}
        </p>
        <span className="hidden h-3.5 w-px bg-border sm:block" aria-hidden="true" />
        <Stat value={foundCount} label={t('intro.statFound')} />
        {isRunning && (
          <span className="flex items-center gap-1.5 text-xs font-medium text-emerald-600 dark:text-emerald-400">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" aria-hidden="true" />
            {t('execution.processing')}
          </span>
        )}
      </div>

      <Button variant="outline" size="sm" className="lg:hidden" onClick={onOpenFilters}>
        <SlidersHorizontal className="h-3.5 w-3.5" />
        {t('intro.openFilters')}
      </Button>
    </div>
  );
}
