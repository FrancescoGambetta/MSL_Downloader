import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ShieldCheck, AlertTriangle, Loader2, RotateCcw, Wrench } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Panel, PanelHeader, PanelTitle, PanelBody, PanelFooter } from '@/components/ui/panel';
import { Section, FieldLabel } from '@/components/ui/section';
import { StatTile } from '@/components/ui/metric';
import { useAppSettings } from '@/lib/AppSettingsContext';
import {
  getStatus,
  getIntegrityLastSol,
  getIntegrityEstimate,
  startIntegrityCheck,
  getJob,
  getLatestJob,
  cancelJob,
  retryFailedIntegrity,
  repairIntegrity,
  CAMERA_KEYS,
  CAMERA_LABELS,
} from '@/lib/catalogManagerApi';

const POLL_MS = 2000;
const LIVE_STATUSES = ['queued', 'running', 'cancelling'];

function formatDuration(seconds) {
  if (seconds == null) return '—';
  const value = Math.max(0, Math.round(seconds));
  const hours = Math.floor(value / 3600);
  const minutes = Math.max(1, Math.floor((value % 3600) / 60)) || (value ? 1 : 0);
  return hours ? `${hours} h ${minutes} min` : `${minutes} min`;
}

export default function CatalogVerify({ kind }) {
  const { t } = useAppSettings();
  const [status, setStatus] = useState(null);
  const [camera, setCamera] = useState(null);
  const [solStart, setSolStart] = useState(0);
  const [solEnd, setSolEnd] = useState(0);
  const [estimate, setEstimate] = useState(null);
  const [job, setJob] = useState(null);
  const [repairJob, setRepairJob] = useState(null);
  const [startError, setStartError] = useState(null);
  const pollRef = useRef(null);
  const repairPollRef = useRef(null);

  const cameras = useMemo(() => (status ? CAMERA_KEYS.filter((c) => (status.cameras || {})[c]) : []), [status]);

  useEffect(() => {
    getStatus(kind).then((data) => {
      setStatus(data);
      const firstCamera = CAMERA_KEYS.find((c) => (data.cameras || {})[c]) || null;
      setCamera(firstCamera);
    });
    setJob(null);
    setRepairJob(null);
    // An integrity check is a detached subprocess (catalog_manager/jobs.py):
    // it keeps running server-side even if this tab unmounts (switch tabs,
    // navigate away). Without this, coming back would show no job and no
    // Stop button at all -- same remount bug already fixed on the Updates
    // and Personalize tabs. Also re-selects the job's own camera, since the
    // running-job view below is keyed off the `camera` state.
    getLatestJob(kind, 'integrity_check')
      .then((existing) => {
        if (existing && LIVE_STATUSES.includes(existing.status)) {
          setJob(existing);
          if (existing.camera) setCamera(existing.camera);
        }
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind]);

  useEffect(() => {
    if (!camera || !status) return;
    const defaultEnd = (status.camera_sol_max || {})[camera] ?? status.sol_max ?? 0;
    getIntegrityLastSol(kind, camera).then(({ last_checked_sol }) => {
      const start = last_checked_sol != null ? Math.min(last_checked_sol + 1, defaultEnd) : 0;
      setSolStart(start);
      setSolEnd(defaultEnd);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera, status, kind]);

  useEffect(() => {
    if (!camera) return;
    const timer = setTimeout(() => {
      getIntegrityEstimate(kind, camera, solStart, solEnd)
        .then(setEstimate)
        .catch(() => setEstimate(null));
    }, 300);
    return () => clearTimeout(timer);
  }, [kind, camera, solStart, solEnd]);

  // Poll the running integrity job every 2s.
  useEffect(() => {
    if (!job || !LIVE_STATUSES.includes(job.status)) {
      clearInterval(pollRef.current);
      return;
    }
    pollRef.current = setInterval(() => {
      getJob(job.job_id).then(setJob).catch(() => {});
    }, POLL_MS);
    return () => clearInterval(pollRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.job_id, job?.status]);

  useEffect(() => {
    if (!repairJob || !LIVE_STATUSES.includes(repairJob.status)) {
      clearInterval(repairPollRef.current);
      return;
    }
    repairPollRef.current = setInterval(() => {
      getJob(repairJob.job_id).then(setRepairJob).catch(() => {});
    }, POLL_MS);
    return () => clearInterval(repairPollRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repairJob?.job_id, repairJob?.status]);

  const handleRun = () => {
    setStartError(null);
    setRepairJob(null);
    startIntegrityCheck(kind, camera, solStart, solEnd)
      .then(setJob)
      .catch((err) => setStartError(err.message || String(err)));
  };

  const handleStop = () => job && cancelJob(job.job_id);

  const handleRetryFailed = () => {
    if (!job) return;
    retryFailedIntegrity(job.job_id, kind).then(setJob).catch((err) => setStartError(err.message || String(err)));
  };

  const handleRepair = () => {
    if (!job) return;
    repairIntegrity(job.job_id, kind).then(setRepairJob).catch((err) => setStartError(err.message || String(err)));
  };

  const running = job && LIVE_STATUSES.includes(job.status);
  const finished = job && !LIVE_STATUSES.includes(job.status);
  const missing = job?.missing_products || 0;
  const failed = job?.failed_locations || 0;
  const groupsTotal = job?.locations_total || 0;
  const groupsDone = job?.locations_done || 0;
  const repairRunning = repairJob && LIVE_STATUSES.includes(repairJob.status);

  return (
    <div className="space-y-8">
      <Section icon={ShieldCheck} eyebrow={t('cat.vf.title')} description={t('cat.vf.desc')}>
        <Panel className="max-w-2xl">
          <PanelBody className="space-y-4">
            <div>
              <FieldLabel className="mb-1.5">{t('cat.vf.camera')}</FieldLabel>
              <div className="flex flex-wrap gap-1.5">
                {cameras.map((cam) => (
                  <button
                    key={cam}
                    type="button"
                    onClick={() => setCamera(cam)}
                    className={`rounded-md border px-2.5 py-1 text-xs font-medium transition-colors ${
                      camera === cam
                        ? 'border-primary/40 bg-primary/10 text-foreground'
                        : 'border-border text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    {CAMERA_LABELS[cam] || cam}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <FieldLabel className="mb-1.5">{t('download.solStart')}</FieldLabel>
                <Input
                  type="number"
                  value={solStart}
                  onChange={(e) => setSolStart(Number(e.target.value))}
                  className="h-8 font-mono text-sm tabular-nums"
                />
              </div>
              <div>
                <FieldLabel className="mb-1.5">{t('download.solEnd')}</FieldLabel>
                <Input
                  type="number"
                  value={solEnd}
                  onChange={(e) => setSolEnd(Number(e.target.value))}
                  className="h-8 font-mono text-sm tabular-nums"
                />
              </div>
            </div>
            {estimate && (
              <p className="text-[11px] text-muted-foreground">
                {t('cat.up.estimate')}: ~{formatDuration(estimate.low_seconds)}–{formatDuration(estimate.high_seconds)}
              </p>
            )}
            {startError && <p className="text-xs text-destructive">{startError}</p>}
          </PanelBody>
          <PanelFooter>
            {running ? (
              <Button variant="outline" className="w-full" onClick={handleStop} disabled={job.status === 'cancelling'}>
                {t('cat.vf.running')}
              </Button>
            ) : (
              <Button onClick={handleRun} disabled={!camera} className="w-full">
                <ShieldCheck className="h-4 w-4" />
                {t('cat.vf.run')}
              </Button>
            )}
          </PanelFooter>
        </Panel>
      </Section>

      {running && (
        <Section eyebrow={t('cat.vf.running')}>
          <Panel className="max-w-2xl">
            <PanelBody className="space-y-2">
              <p className="flex items-center gap-2 text-xs font-medium">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {groupsTotal ? `${t('cat.vf.groups')}: ${groupsDone}/${groupsTotal}` : t('cat.vf.running')}
              </p>
            </PanelBody>
          </Panel>
        </Section>
      )}

      {finished && (
        <Section eyebrow={t('cat.vf.resultTitle')}>
          <div className="max-w-2xl space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <StatTile label={t('cat.vf.groups')} value={groupsTotal} />
              <StatTile label={t('cat.vf.missing')} value={missing} tone={missing > 0 ? 'warning' : 'default'} />
              <StatTile label={t('cat.vf.failed')} value={failed} tone={failed > 0 ? 'warning' : 'default'} />
            </div>

            {job.status === 'failed' && job.error && (
              <Panel>
                <PanelBody className="flex items-start gap-3">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden="true" />
                  <p className="text-xs text-destructive">{job.error}</p>
                </PanelBody>
              </Panel>
            )}

            {failed > 0 && (
              <Panel>
                <PanelBody className="flex items-start gap-3">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" aria-hidden="true" />
                  <div className="min-w-0 space-y-1">
                    <p className="text-xs font-medium">{t('cat.vf.partial')}</p>
                    <p className="text-[11px] leading-relaxed text-muted-foreground">{t('cat.vf.partialDesc')}</p>
                  </div>
                </PanelBody>
                <PanelFooter>
                  <Button variant="outline" size="sm" onClick={handleRetryFailed}>
                    <RotateCcw className="h-3.5 w-3.5" />
                    {t('cat.vf.retry')}
                  </Button>
                </PanelFooter>
              </Panel>
            )}

            {missing > 0 && (
              <Panel>
                <PanelHeader>
                  <PanelTitle>
                    {t('cat.vf.missing')} · {CAMERA_LABELS[camera] || camera}
                  </PanelTitle>
                </PanelHeader>
                {repairRunning ? (
                  <PanelBody className="flex items-center gap-2 text-xs">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    {repairJob.phase || t('cat.vf.addMissing')}
                  </PanelBody>
                ) : repairJob?.status === 'completed' ? (
                  <PanelBody className="text-xs text-emerald-600 dark:text-emerald-400">
                    +{repairJob.new_products || 0}
                  </PanelBody>
                ) : (
                  <PanelFooter>
                    <Button size="sm" className="w-full" onClick={handleRepair}>
                      <Wrench className="h-3.5 w-3.5" />
                      {t('cat.vf.addMissing')}
                    </Button>
                  </PanelFooter>
                )}
              </Panel>
            )}
          </div>
        </Section>
      )}
    </div>
  );
}
