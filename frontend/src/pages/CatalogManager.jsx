import React, { useEffect, useState } from 'react';
import { Database, Settings, Loader2 } from 'lucide-react';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { Button } from '@/components/ui/button';
import AppHeader from '@/components/layout/AppHeader';
import SettingsPanel from '@/components/settings/SettingsPanel';
import CatalogSetup from '@/components/catalog/CatalogSetup';
import CatalogShell from '@/components/catalog/CatalogShell';
import CatalogOverview from '@/components/catalog/tabs/CatalogOverview';
import CatalogUpdates from '@/components/catalog/tabs/CatalogUpdates';
import CatalogVerify from '@/components/catalog/tabs/CatalogVerify';
import CatalogComposition from '@/components/catalog/tabs/CatalogComposition';
import CatalogPersonalize from '@/components/catalog/tabs/CatalogPersonalize';
import { getStatus } from '@/lib/catalogManagerApi';

const SETUP_KEY = 'catalog_setup_complete';

const TAB_CONTENT = {
  overview: CatalogOverview,
  updates: CatalogUpdates,
  verify: CatalogVerify,
  composition: CatalogComposition,
  custom: CatalogPersonalize,
};

export default function CatalogManager() {
  const { t } = useAppSettings();
  // Real backend check on mount (both catalogs' Parquet must exist), rather
  // than trusting a possibly-stale localStorage flag from an earlier mockup
  // run -- null while the check is in flight.
  const [setupComplete, setSetupComplete] = useState(null);
  const [activeTab, setActiveTab] = useState('overview');
  const [kind, setKind] = useState('pds');
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    Promise.all([getStatus('pds'), getStatus('raw')])
      .then(([pds, raw]) => setSetupComplete(Boolean(pds.exists && raw.exists)))
      .catch(() => setSetupComplete(localStorage.getItem(SETUP_KEY) === 'true'));
  }, []);

  useEffect(() => {
    document.title = setupComplete ? t('cat.title') : t('cat.setup.eyebrow');
  }, [setupComplete, t]);

  const ActiveTab = TAB_CONTENT[activeTab] ?? CatalogOverview;

  return (
    <div className="flex min-h-svh flex-col">
      <AppHeader
        icon={Database}
        title={t('cat.title')}
        subtitle={t('cat.subtitle')}
        actions={
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => setSettingsOpen(true)}
            aria-label={t('header.settings')}
            title={t('header.settings')}
          >
            <Settings className="h-4 w-4" />
          </Button>
        }
      />

      {setupComplete === null ? (
        <div className="flex flex-1 items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('cat.ov.loading')}
        </div>
      ) : !setupComplete ? (
        <CatalogSetup
          onComplete={() => {
            localStorage.setItem(SETUP_KEY, 'true');
            setSetupComplete(true);
          }}
        />
      ) : (
        <CatalogShell activeTab={activeTab} onTabChange={setActiveTab} kind={kind} onKindChange={setKind}>
          <ActiveTab kind={kind} />
        </CatalogShell>
      )}

      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
