import React from 'react';
import { Button } from '@/components/ui/button';
import { Menu, Sun, Moon } from 'lucide-react';
import { useAppSettings } from '@/lib/AppSettingsContext';
import AppSwitch from '@/components/layout/AppSwitch';

// One header serves both apps: the identity block on the left changes, the app
// switcher and the appearance/utility actions on the right do not. Keeping it
// in a single component is what makes the two products feel like one site.
//
// Height is 3.5rem — the sidebar's sticky offset in Home.jsx and the catalog's
// tab strip both key off it, so changing it here means changing it there.
export default function AppHeader({
  icon: Icon,
  title,
  subtitle,
  onToggleSidebar = null,
  actions = null,
}) {
  const { t, settings, update } = useAppSettings();
  const isDark = settings.mode === 'dark';

  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-card/80 px-3 backdrop-blur-xl sm:px-5">
      <div className="flex min-w-0 items-center gap-2">
        {onToggleSidebar && (
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 lg:hidden"
            onClick={onToggleSidebar}
            aria-label={t('header.menu')}
          >
            <Menu className="h-4 w-4" />
          </Button>
        )}
        <div className="flex min-w-0 items-center gap-2.5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary ring-1 ring-inset ring-primary/15">
            <Icon className="h-4 w-4" aria-hidden="true" />
          </div>
          <div className="min-w-0 leading-tight">
            <p className="truncate font-heading text-[13px] font-semibold tracking-tight">
              {title}
            </p>
            <p className="hidden truncate text-[11px] text-muted-foreground md:block">
              {subtitle}
            </p>
          </div>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        <AppSwitch />
        <div className="flex items-center gap-0.5">
          {actions}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => update({ mode: isDark ? 'light' : 'dark' })}
            aria-label={isDark ? t('settings.light') : t('settings.dark')}
            title={isDark ? t('settings.light') : t('settings.dark')}
          >
            {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </header>
  );
}
