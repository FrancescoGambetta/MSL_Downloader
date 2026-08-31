import React from 'react';
import { LayoutGrid, RefreshCw, ShieldCheck, Layers, SlidersHorizontal } from 'lucide-react';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { CATALOG_KINDS } from '@/lib/catalogData';
import { cn } from '@/lib/utils';

export const TABS = [
  { id: 'overview', icon: LayoutGrid, key: 'cat.tab.overview' },
  { id: 'updates', icon: RefreshCw, key: 'cat.tab.updates' },
  { id: 'verify', icon: ShieldCheck, key: 'cat.tab.verify' },
  { id: 'composition', icon: Layers, key: 'cat.tab.composition' },
  { id: 'custom', icon: SlidersHorizontal, key: 'cat.tab.custom' },
];

// The mockups stacked three bars: header, catalog picker, tabs. That is a lot
// of chrome before any content. Tabs and the PDS/RAW picker live on one line
// instead — they are different axes of the same question ("which view of which
// catalog"), and the picker reads as the scope the tabs operate on.
export default function CatalogShell({ activeTab, onTabChange, kind, onKindChange, children }) {
  const { t } = useAppSettings();

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="sticky top-14 z-20 border-b border-border bg-card/80 backdrop-blur-xl">
        <div className="mx-auto flex w-full max-w-[1400px] items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <nav
            className="-mb-px flex min-w-0 overflow-x-auto"
            role="tablist"
            aria-label={t('cat.title')}
          >
            {TABS.map(({ id, icon: Icon, key }) => {
              const active = activeTab === id;
              return (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => onTabChange(id)}
                  className={cn(
                    'flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2.5 text-xs font-medium transition-colors',
                    'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
                    active
                      ? 'border-primary text-foreground'
                      : 'border-transparent text-muted-foreground hover:text-foreground'
                  )}
                >
                  <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                  {t(key)}
                </button>
              );
            })}
          </nav>

          <div
            className="my-1.5 flex shrink-0 items-center gap-0.5 rounded-md border border-border bg-muted/60 p-0.5"
            role="group"
            aria-label="Catalogo"
          >
            {CATALOG_KINDS.map(({ id, label }) => (
              <button
                key={id}
                type="button"
                aria-pressed={kind === id}
                onClick={() => onKindChange(id)}
                className={cn(
                  'rounded px-2 py-1 font-mono text-[11px] font-medium uppercase tracking-wider transition-colors',
                  'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
                  kind === id
                    ? 'bg-card text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground'
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <main className="min-h-0 flex-1">
        <div className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8">{children}</div>
      </main>
    </div>
  );
}
