import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { LogOut, X, UserCircle } from 'lucide-react';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { useAuth } from '@/lib/AuthContext';
import { useDismissable } from '@/hooks/use-dismissable';
import { useMediaQuery, DESKTOP_QUERY } from '@/hooks/use-media-query';
import { cn } from '@/lib/utils';

// Off-canvas drawer up to `lg`, a sticky column from `lg` up. Sticking it just
// below the 4rem header lets the filter form scroll on its own while the main
// column keeps the page scrollbar.
export default function AppSidebar({ userName, children, open, onClose }) {
  const { t } = useAppSettings();
  const { logout } = useAuth();
  const navigate = useNavigate();
  const isDesktop = useMediaQuery(DESKTOP_QUERY);

  // Logout ends the session server-side (see AuthContext.jsx) but on its own
  // leaves `user` null while staying on this same page -- nothing then stops
  // the app from being used name-less. Send back to the login screen instead,
  // consistent with "/" being the one real entry point (see App.jsx/Landing.jsx).
  const handleLogout = () => {
    logout();
    navigate('/');
  };

  // Escape and the scroll lock only apply while it is actually an overlay.
  useDismissable(open && !isDesktop, onClose);

  // Widening past `lg` docks the sidebar, so the drawer state has to be
  // released — otherwise the lock and overlay would outlive the drawer.
  useEffect(() => {
    if (isDesktop && open) onClose();
  }, [isDesktop, open, onClose]);

  return (
    <>
      {open && !isDesktop && (
        <div
          className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm animate-in fade-in duration-200 lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 flex w-[310px] max-w-[86vw] flex-col border-r border-sidebar-border bg-sidebar',
          'transition-transform duration-300 ease-out',
          !open && 'max-lg:-translate-x-full',
          'lg:sticky lg:top-14 lg:z-20 lg:h-[calc(100svh-3.5rem)] lg:w-[310px] lg:max-w-none'
        )}
      >
        {/* Close button: mobile only, compact */}
        <div className="flex items-center justify-end gap-1 border-b border-sidebar-border bg-sidebar-accent/20 px-2 py-1.5 lg:hidden">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={onClose}
            aria-label={t('common.close')}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Filters: flexible, scrollable */}
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">{children}</div>

        {/* Profile: fixed at bottom, compact on mobile */}
        <div className="shrink-0 border-t border-sidebar-border bg-sidebar-accent/30 px-2.5 py-2 sm:px-3 sm:py-2.5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2 sm:gap-2.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/15 sm:h-9 sm:w-9">
                <UserCircle className="h-4 w-4 text-primary sm:h-5 sm:w-5" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <p className="text-[10px] text-muted-foreground sm:text-xs">{t('sidebar.profile')}</p>
                <p className="truncate text-xs font-medium sm:text-sm">{userName}</p>
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 shrink-0 text-muted-foreground hover:text-destructive sm:h-8 sm:w-8"
              onClick={handleLogout}
              aria-label={t('header.logout')}
              title={t('header.logout')}
            >
              <LogOut className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
            </Button>
          </div>
        </div>
      </aside>
    </>
  );
}
