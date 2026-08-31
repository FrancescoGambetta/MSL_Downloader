import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Telescope, Database } from 'lucide-react';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { cn } from '@/lib/utils';

// The two apps are separate products that share a domain, a theme and a
// settings store. A segmented control — rather than a link on one side and a
// back arrow on the other — states that relationship: you are always in one of
// two places, and the other one is a peer, not a sub-page.
//
// Below `sm` the labels drop and the segments become icon squares, which keeps
// the header from wrapping on a phone.

const APPS = [
  { path: '/download', icon: Telescope, key: 'switch.downloader' },
  { path: '/catalog-manager', icon: Database, key: 'switch.catalog' },
];

export default function AppSwitch({ className = '' }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { t } = useAppSettings();

  return (
    <div
      className={cn(
        'flex shrink-0 items-center gap-0.5 rounded-lg border border-border bg-muted/60 p-0.5',
        className
      )}
      role="tablist"
      aria-label={t('switch.label')}
    >
      {APPS.map(({ path, icon: Icon, key }) => {
        const active = pathname === path;
        return (
          <button
            key={path}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => navigate(path)}
            className={cn(
              'flex h-7 items-center gap-1.5 rounded-md px-2 text-xs font-medium transition-colors sm:px-2.5',
              'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
              active
                ? 'bg-card text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            )}
          >
            <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span className="hidden whitespace-nowrap sm:inline">{t(key)}</span>
            <span className="sr-only sm:hidden">{t(key)}</span>
          </button>
        );
      })}
    </div>
  );
}
