import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Compass, Home } from 'lucide-react';
import { useAppSettings } from '@/lib/AppSettingsContext';

export default function NotFound() {
  const { pathname } = useLocation();
  const { t } = useAppSettings();

  return (
    <div className="flex min-h-svh items-center justify-center px-6 py-16">
      <div className="w-full max-w-md space-y-7 text-center">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10 ring-1 ring-primary/20">
          <Compass className="h-7 w-7 text-primary" aria-hidden="true" />
        </div>

        <div className="space-y-3">
          <p className="font-mono text-5xl font-light text-muted-foreground/50">404</p>
          <h1 className="font-heading text-2xl font-semibold tracking-tight">
            {t('notFound.title')}
          </h1>
          <p className="text-sm leading-relaxed text-muted-foreground">
            {t('notFound.body')}
          </p>
          <p className="break-all font-mono text-xs text-muted-foreground/70">{pathname}</p>
        </div>

        <Button asChild>
          <Link to="/">
            <Home className="h-4 w-4" />
            {t('notFound.home')}
          </Link>
        </Button>
      </div>
    </div>
  );
}
