import React, { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Panel, PanelHeader, PanelTitle, PanelBody, PanelFooter } from '@/components/ui/panel';
import { Eyebrow } from '@/components/ui/section';
import { Meter } from '@/components/ui/metric';
import { BookOpen, Download, HardDriveDownload, FileJson, Check } from 'lucide-react';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { cn } from '@/lib/utils';
import {
  startDistributionInstall,
  getDistributionInstallJob,
  saveBootstrapChoice,
  startBootstrapJson,
  getJob,
} from '@/lib/catalogManagerApi';

const STEPS = ['explain', 'install', 'json'];
const POLL_MS = 800;

// Mandatory first run: explain what a catalog is, install PDS + RAW (via the
// real distribution.py download+verify+atomic-swap, skipped instantly if the
// local file already matches the release's SHA-256), then let the user decide
// whether to also generate the editable JSON (catalog_manager.jobs' real
// bootstrap_json job).
export default function CatalogSetup({ onComplete }) {
  const { t } = useAppSettings();
  const [step, setStep] = useState('explain');
  const [progress, setProgress] = useState({ pds: 0, raw: 0 });
  const [installError, setInstallError] = useState(null);
  const [generating, setGenerating] = useState(0);
  const timers = useRef([]);

  useEffect(() => () => timers.current.forEach(clearInterval), []);
  const track = (id) => {
    timers.current.push(id);
    return id;
  };

  const pollInstall = (catalog, jobId) => {
    const id = track(
      setInterval(() => {
        getDistributionInstallJob(jobId)
          .then((job) => {
            const pct = job.total ? Math.min(100, Math.round((job.downloaded / job.total) * 100)) : job.status === 'completed' ? 100 : 0;
            setProgress((prev) => ({ ...prev, [catalog]: pct }));
            if (job.status === 'completed' || job.status === 'failed') {
              clearInterval(id);
              setProgress((prev) => ({ ...prev, [catalog]: 100 }));
              if (job.status === 'failed') setInstallError(job.error || 'Install failed');
            }
          })
          .catch(() => clearInterval(id));
      }, POLL_MS)
    );
  };

  const startInstall = () => {
    setStep('install');
    setInstallError(null);
    startDistributionInstall('pds').then(({ job_id }) => pollInstall('pds', job_id));
    startDistributionInstall('raw').then(({ job_id }) => pollInstall('raw', job_id));
  };

  useEffect(() => {
    if (step === 'install' && progress.pds >= 100 && progress.raw >= 100 && !installError) {
      const id = track(setTimeout(() => setStep('json'), 400));
      return () => clearTimeout(id);
    }
  }, [step, progress, installError]);

  const chooseJson = (withJson) => {
    if (!withJson) {
      saveBootstrapChoice('download_only').finally(onComplete);
      return;
    }
    saveBootstrapChoice('generate')
      .then(() => startBootstrapJson())
      .then((job) => {
        setGenerating(1);
        const id = track(
          setInterval(() => {
            getJob(job.job_id)
              .then((fresh) => {
                const total = fresh.rows_total || 1;
                const done = fresh.rows_done || 0;
                setGenerating(Math.max(1, Math.min(100, Math.round((done / total) * 100))));
                if (fresh.status !== 'queued' && fresh.status !== 'running') {
                  clearInterval(id);
                  onComplete();
                }
              })
              .catch(() => clearInterval(id));
          }, POLL_MS)
        );
      })
      .catch(() => onComplete());
  };

  const stepIndex = STEPS.indexOf(step);

  return (
    <main className="flex flex-1 items-center justify-center px-4 py-10">
      <div className="w-full max-w-lg space-y-5">
        <div className="flex items-center justify-between gap-4">
          <Eyebrow className="text-xs">{t('cat.setup.eyebrow')}</Eyebrow>
          <div className="flex items-center gap-1.5" aria-label={t('cat.setup.step', { n: stepIndex + 1 })}>
            {STEPS.map((s, i) => (
              <span
                key={s}
                className={cn(
                  'h-1 rounded-full transition-all duration-300',
                  i < stepIndex ? 'w-4 bg-primary/40' : i === stepIndex ? 'w-6 bg-primary' : 'w-4 bg-border'
                )}
                aria-hidden="true"
              />
            ))}
          </div>
        </div>

        {step === 'explain' && (
          <Panel>
            <PanelHeader className="py-4">
              <PanelTitle icon={BookOpen} className="text-lg [&_svg]:h-5 [&_svg]:w-5">
                {t('cat.setup.whatTitle')}
              </PanelTitle>
            </PanelHeader>
            <PanelBody className="space-y-5 py-5">
              <p className="text-base leading-relaxed text-muted-foreground">{t('cat.setup.whatBody')}</p>
              <ul className="space-y-3">
                {['cat.setup.point1', 'cat.setup.point2', 'cat.setup.point3'].map((k) => (
                  <li key={k} className="flex items-start gap-3 text-sm">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                    <span>{t(k)}</span>
                  </li>
                ))}
              </ul>
            </PanelBody>
            <PanelFooter className="py-4">
              <Button className="h-11 w-full text-base" onClick={startInstall}>
                <Download className="h-5 w-5" />
                {t('cat.setup.install')}
              </Button>
            </PanelFooter>
          </Panel>
        )}

        {step === 'install' && (
          <Panel>
            <PanelHeader>
              <PanelTitle icon={HardDriveDownload}>{t('cat.setup.installTitle')}</PanelTitle>
            </PanelHeader>
            <PanelBody className="space-y-4">
              <Meter label="Catalogo PDS" value={progress.pds} display={`${Math.round(progress.pds)}%`} tone={progress.pds >= 100 ? 'positive' : 'accent'} />
              <Meter label="RAW Archive" value={progress.raw} display={`${Math.round(progress.raw)}%`} tone={progress.raw >= 100 ? 'positive' : 'accent'} />
              {installError && <p className="text-xs text-destructive">{installError}</p>}
              <p className="text-[11px] leading-relaxed text-muted-foreground">{t('cat.setup.installBody')}</p>
            </PanelBody>
          </Panel>
        )}

        {step === 'json' && (
          <Panel>
            <PanelHeader>
              <PanelTitle icon={FileJson}>{t('cat.setup.jsonTitle')}</PanelTitle>
            </PanelHeader>
            <PanelBody className="space-y-4">
              <p className="text-sm leading-relaxed text-muted-foreground">{t('cat.setup.jsonBody')}</p>

              {generating > 0 ? (
                <Meter label={t('cat.setup.generating')} value={generating} display={`${Math.min(100, Math.round(generating))}%`} />
              ) : (
                <div className="grid gap-2.5 sm:grid-cols-2">
                  <ChoiceCard title={t('cat.setup.parquetOnly')} description={t('cat.setup.parquetOnlyDesc')} onClick={() => chooseJson(false)} />
                  <ChoiceCard
                    title={t('cat.setup.withJson')}
                    description={t('cat.setup.withJsonDesc')}
                    onClick={() => chooseJson(true)}
                    recommended
                  />
                </div>
              )}
            </PanelBody>
          </Panel>
        )}
      </div>
    </main>
  );
}

function ChoiceCard({ title, description, onClick, recommended = false }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'rounded-lg border p-3 text-left transition-colors',
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
        recommended ? 'border-primary/40 bg-primary/5 hover:bg-primary/10' : 'border-border hover:border-primary/40 hover:bg-accent/40'
      )}
    >
      <p className="text-[13px] font-semibold">{title}</p>
      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{description}</p>
    </button>
  );
}
