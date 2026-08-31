import React, { useCallback, useMemo, useState } from 'react';
import { Telescope, HelpCircle, Settings } from 'lucide-react';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { useAuth } from '@/lib/AuthContext';
import { useDownloader } from '@/lib/useDownloader';
import { Button } from '@/components/ui/button';
import AppHeader from '@/components/layout/AppHeader';
import AppSidebar from '@/components/layout/AppSidebar';
import PageIntro from '@/components/layout/PageIntro';
import SettingsPanel from '@/components/settings/SettingsPanel';
import HelpDialog from '@/components/settings/HelpDialog';
import DownloadPreparation from '@/components/download/DownloadPreparation';
import AppliedFilters from '@/components/download/AppliedFilters';
import LiveLog from '@/components/download/LiveLog';
import ConfirmDialog from '@/components/download/ConfirmDialog';
import ImageResults from '@/components/results/ImageResults';
import ImageViewport from '@/components/results/ImageViewport';
import MetadataPanel from '@/components/results/MetadataPanel';

// Above this many products the run asks for confirmation first.
const CONFIRM_THRESHOLD = 25;

export default function Home() {
  const { settings, t } = useAppSettings();
  const { user } = useAuth();
  const dl = useDownloader();

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [confirmLimit, setConfirmLimit] = useState('');

  const userName = useMemo(
    () => user?.full_name || user?.email?.split('@')[0] || 'Explorer',
    [user]
  );

  const handleApply = useCallback(
    (filters) => {
      dl.applyFilters({
        ...filters,
        outputFolder: settings.outputFolder,
      });
      setSidebarOpen(false);
    },
    [dl, settings.outputFolder]
  );

  const doRun = useCallback(
    (limit) => {
      const records = limit > 0 ? dl.foundRecords.slice(0, limit) : dl.foundRecords;
      dl.runDownload(records);
      setShowConfirm(false);
    },
    [dl]
  );

  const startDownload = useCallback(() => {
    if (dl.foundRecords.length > CONFIRM_THRESHOLD) {
      setConfirmLimit(String(dl.foundRecords.length));
      setShowConfirm(true);
    } else {
      doRun(0);
    }
  }, [dl.foundRecords.length, doRun]);

  return (
    <div className="flex min-h-svh flex-col">
      <AppHeader
        icon={Telescope}
        title={t('app.title')}
        subtitle={t('app.subtitle')}
        onToggleSidebar={() => setSidebarOpen((open) => !open)}
        actions={
          <>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={() => setHelpOpen(true)}
              aria-label={t('header.help')}
              title={t('header.help')}
            >
              <HelpCircle className="h-4 w-4" />
            </Button>
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
          </>
        }
      />

      <div className="flex flex-1 items-stretch">
        <AppSidebar
          userName={userName}
          open={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
        >
          <DownloadPreparation onApply={handleApply} isSearching={dl.isSearching} />
        </AppSidebar>

        <main className="min-w-0 flex-1">
          <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-5 px-4 py-5 sm:px-6 sm:py-6 lg:px-8">
            <PageIntro
              foundCount={dl.appliedFilters?.afterFilters ?? 0}
              isRunning={dl.isRunning}
              onOpenFilters={() => setSidebarOpen(true)}
            />

            <section className="grid gap-4 lg:grid-cols-5">
              <AppliedFilters
                className="lg:col-span-2"
                appliedFilters={dl.appliedFilters}
                isRunning={dl.isRunning}
                onStart={startDownload}
                onStop={dl.stop}
              />
              <LiveLog
                className="lg:col-span-3"
                log={dl.log}
                progress={dl.progress}
                isRunning={dl.isRunning}
                onClear={dl.clearLog}
              />
            </section>

            <section className="grid gap-4 md:grid-cols-2 xl:h-[32rem] xl:grid-cols-12">
              <ImageResults
                className="md:col-span-2 xl:col-span-3"
                images={dl.savedImages}
                selectedImage={dl.selectedImage}
                onSelect={dl.setSelectedImage}
                onClear={dl.clearSaved}
              />
              <ImageViewport className="xl:col-span-5" image={dl.selectedImage} />
              <MetadataPanel className="xl:col-span-4" image={dl.selectedImage} />
            </section>
          </div>
        </main>
      </div>

      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <HelpDialog open={helpOpen} onClose={() => setHelpOpen(false)} />
      <ConfirmDialog
        open={showConfirm}
        count={dl.foundRecords.length}
        limit={confirmLimit}
        setLimit={setConfirmLimit}
        onCancel={() => setShowConfirm(false)}
        onConfirm={() => doRun(Number(confirmLimit) || 0)}
      />
    </div>
  );
}
