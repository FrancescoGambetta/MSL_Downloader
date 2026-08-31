import React, { useCallback, useEffect, useRef, useState } from 'react';
import { RefreshCw, Play, CheckCircle2, Loader2, AlertTriangle, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Panel, PanelHeader, PanelTitle, PanelBody, PanelFooter } from '@/components/ui/panel';
import { Section } from '@/components/ui/section';
import { useAppSettings } from '@/lib/AppSettingsContext';
import {
  getStatusFull,
  checkUpdates,
  startCatalogUpdate,
  getJob,
  getJobLog,
  getLatestJob,
  cancelJob,
  CAMERA_LABELS,
} from '@/lib/catalogManagerApi';
import RawLiveLog from '@/components/catalog/RawLiveLog';
import { parseProgress } from '@/lib/rawJobLog';
import { cn } from '@/lib/utils';

// Real backend phases (pds_update_worker.py / raw_update_worker.py) mapped onto
// the dashboard's own phase labels -- RAW never emits "enriching_metadata",
// PDS never skips it, so not every phase applies to every catalog kind.
const PHASE_LABEL_KEY = {
  preparing_working_copy: 'cat.up.phase1',
  scanning_nasa: 'cat.up.phase2',
  enriching_metadata: 'cat.up.phase3',
  validating_working_copy: 'cat.up.phase5',
  installing_catalog: 'cat.up.phase6',
};

const POLL_MS = 2000;

export default function CatalogUpdates({ kind }) {
  const { t } = useAppSettings();
  const [status, setStatus] = useState(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState(null);
  const [newCameras, setNewCameras] = useState([]);
  const [selectedCameras, setSelectedCameras] = useState([]);
  const [job, setJob] = useState(null);
  const [startError, setStartError] = useState(null);
  const [logText, setLogText] = useState('');
  const pollRef = useRef(null);

  const loadLocal = useCallback(() => {
    getStatusFull(kind).then(setStatus).catch(() => {});
  }, [kind]);

  useEffect(() => {
    loadLocal();
    setNewCameras([]);
    setSelectedCameras([]);
    setJob(null);
    setLogText('');
    getLatestJob(kind, 'catalog_update')
      .then((existing) => {
        if (existing && ['queued', 'running', 'cancelling'].includes(existing.status)) {
          setJob(existing);
          getJobLog(existing.job_id).then((r) => setLogText(r.log)).catch(() => {});
        }
      })
      .catch(() => {});
  }, [kind, loadLocal]);

  // Poll the active update job (status + its worker's live log text) every 2s,
  // mirroring the Streamlit dashboard's own @st.fragment(run_every="2s") panel
  // and its log-tail expander.
  useEffect(() => {
    if (!job || !['queued', 'running', 'cancelling'].includes(job.status)) {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }
    pollRef.current = setInterval(() => {
      getJob(job.job_id)
        .then((fresh) => {
          setJob(fresh);
          if (!['queued', 'running', 'cancelling'].includes(fresh.status)) {
            loadLocal();
          }
        })
        .catch(() => {});
      getJobLog(job.job_id).then((r) => setLogText(r.log)).catch(() => {});
    }, POLL_MS);
    return () => clearInterval(pollRef.current);
  }, [job?.job_id, job?.status]);

  const handleCheck = () => {
    setChecking(true);
    setCheckError(null);
    // A finished job (completed/failed/cancelled) from a previous check must
    // not linger once a fresh check starts -- otherwise its stale summary
    // (e.g. "+8801 total products") keeps showing next to the newly detected
    // Sols, which belong to an unrelated run.
    if (job && !['queued', 'running', 'cancelling'].includes(job.status)) {
      setJob(null);
      setLogText('');
    }
    checkUpdates(kind)
      .then((fresh) => {
        setStatus(fresh);
        const remoteByCamera = fresh.remote_by_camera || {};
        const checkedByCamera = fresh.camera_last_checked || {};
        const detected = Object.entries(remoteByCamera)
          .filter(([camera, sol]) => Number(sol) > Number(checkedByCamera[camera] ?? -1))
          .map(([camera, sol]) => ({ camera, sol, checked: checkedByCamera[camera] ?? -1 }));
        setNewCameras(detected);
        setSelectedCameras(kind === 'pds' ? (detected[0] ? [detected[0].camera] : []) : detected.map((d) => d.camera));
      })
      .catch((err) => setCheckError(err.message || String(err)))
      .finally(() => setChecking(false));
  };

  const toggleCamera = (camera) => {
    setSelectedCameras((prev) => {
      if (kind === 'pds') return prev.includes(camera) ? [] : [camera];
      return prev.includes(camera) ? prev.filter((c) => c !== camera) : [...prev, camera];
    });
  };

  const handleRun = () => {
    if (!selectedCameras.length) return;
    const relevant = newCameras.filter((n) => selectedCameras.includes(n.camera));
    const solStart = Math.min(...relevant.map((n) => n.checked + 1));
    const solEnd = Math.max(...relevant.map((n) => n.sol));
    setStartError(null);
    startCatalogUpdate(kind, solStart, solEnd, selectedCameras)
      .then(setJob)
      .catch((err) => setStartError(err.message || String(err)));
  };

  const handleStop = () => {
    if (job) cancelJob(job.job_id);
  };

  const jobRunning = job && ['queued', 'running', 'cancelling'].includes(job.status);
  const phaseKey = job?.phase ? PHASE_LABEL_KEY[job.phase] : null;
  const progress = jobRunning ? parseProgress(logText, job) : null;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
    <div className="space-y-8">
      <Section icon={RefreshCw} eyebrow={t('cat.up.checkTitle')} description={t('cat.up.checkDesc')}>
        <Panel className="max-w-2xl">
          <PanelBody className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="font-mono text-sm font-medium tabular-nums">
                Sol {(status?.sol_max ?? 0).toLocaleString()}
                {status?.remote_latest_sol != null ? ` → ${status.remote_latest_sol.toLocaleString()}` : ''}
              </p>
              {newCameras.length > 0 && (
                <p className="mt-1 flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400">
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                  {t('cat.up.resultTitle')}: {newCameras.map((n) => CAMERA_LABELS[n.camera] || n.camera).join(', ')}
                </p>
              )}
              {checkError && <p className="mt-1 text-xs text-destructive">{checkError}</p>}
            </div>
            <Button onClick={handleCheck} disabled={checking} size="sm" variant="outline" className="shrink-0">
              {checking ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              {checking ? t('cat.up.checking') : t('cat.up.check')}
            </Button>
          </PanelBody>
        </Panel>
      </Section>

      {(newCameras.length > 0 || job) && (
        // Gated on newCameras OR job (not just newCameras) so a job restored
        // on remount (see the initial-mount effect above, which only ever
        // restores `job` -- never repopulates `newCameras`) keeps this panel,
        // and with it the Stop button, visible. Without the `|| job`, an
        // active job survives the remount server-side but its Stop control
        // disappears client-side until the next "Check for updates".
        <Section icon={Play} eyebrow={t('cat.up.runTitle')} description={t('cat.up.runDesc')}>
          <Panel className="max-w-2xl">
            <PanelHeader>
              <PanelTitle>{t('cat.up.affected')}</PanelTitle>
            </PanelHeader>
            <PanelBody className="space-y-3">
              {!jobRunning && (
                <div className="flex flex-wrap gap-1.5">
                  {newCameras.map((n) => (
                    <button
                      key={n.camera}
                      type="button"
                      disabled={job?.status === 'completed'}
                      onClick={() => toggleCamera(n.camera)}
                      className={cn(
                        'rounded-md border px-2.5 py-1 text-xs font-medium transition-colors',
                        job?.status === 'completed'
                          ? 'cursor-not-allowed border-border/50 text-muted-foreground/40'
                          : selectedCameras.includes(n.camera)
                          ? 'border-primary/40 bg-primary/10 text-foreground'
                          : 'border-border text-muted-foreground hover:text-foreground'
                      )}
                    >
                      {CAMERA_LABELS[n.camera] || n.camera} · +{n.sol - n.checked} Sol
                    </button>
                  ))}
                </div>
              )}

              {jobRunning ? (
                <div className="space-y-1.5">
                  <p className="flex items-center gap-2 text-xs font-medium">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    {phaseKey ? t(phaseKey) : t('cat.up.running')}
                  </p>
                  {job.current_camera && <p className="text-[11px] text-muted-foreground">{CAMERA_LABELS[job.current_camera] || job.current_camera}</p>}
                  {progress?.scanned && (
                    <div className="space-y-1">
                      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-primary transition-all"
                          style={{ width: `${Math.min(100, (progress.scanned.done / Math.max(1, progress.scanned.total)) * 100)}%` }}
                        />
                      </div>
                      <p className="text-[11px] text-muted-foreground">
                        {t('cat.up.scanned')}: {progress.scanned.done.toLocaleString()}/{progress.scanned.total.toLocaleString()}
                        {progress.products != null && ` · ${t('cat.up.products')}: ${progress.products.toLocaleString()}`}
                      </p>
                    </div>
                  )}
                </div>
              ) : job ? (
                <div className="space-y-1.5 text-xs">
                  {job.status === 'completed' && (
                    <p className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400">
                      <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                      +{(job.new_products || 0).toLocaleString()} {t('cat.ov.totalProducts').toLowerCase()}
                    </p>
                  )}
                  {job.status === 'failed' && (
                    <p className="flex items-center gap-1.5 text-destructive">
                      <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                      {job.error || t('cat.up.running')}
                    </p>
                  )}
                  {job.status === 'cancelled' && <p className="text-muted-foreground">{t('confirm.cancel')}</p>}
                </div>
              ) : null}
              {startError && <p className="text-xs text-destructive">{startError}</p>}
            </PanelBody>
            <PanelFooter>
              {jobRunning ? (
                <Button
                  variant="destructive"
                  className="w-full"
                  onClick={handleStop}
                  disabled={job.status === 'cancelling'}
                >
                  <Square className="h-4 w-4" />
                  {job.status === 'cancelling' ? t('cat.up.running') : t('cat.up.stop')}
                </Button>
              ) : (
                <Button onClick={handleRun} disabled={!selectedCameras.length || job?.status === 'completed'} className="w-full">
                  <Play className="h-4 w-4" />
                  {t('cat.up.run')}
                </Button>
              )}
            </PanelFooter>
          </Panel>
        </Section>
      )}
    </div>

    <RawLiveLog logText={logText} isLive={jobRunning} onClear={() => setLogText('')} />
    </div>
  );
}
