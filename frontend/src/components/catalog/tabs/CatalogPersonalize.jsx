import React, { useEffect, useMemo, useRef, useState } from 'react';
import { SlidersHorizontal, Plus, Minus, Trash2, Check, Loader2, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Modal } from '@/components/ui/modal';
import { Panel, PanelHeader, PanelTitle, PanelBody, PanelFooter, PanelEmpty } from '@/components/ui/panel';
import { Section, FieldLabel } from '@/components/ui/section';
import { useAppSettings } from '@/lib/AppSettingsContext';
import {
  getCustomizationOptions,
  getCustomizationCurrent,
  startCustomization,
  getJob,
  getJobLog,
  getLatestJob,
  cancelJob,
  getStatus,
  CAMERA_LABELS,
} from '@/lib/catalogManagerApi';
import CodeTooltip from '@/components/catalog/CodeTooltip';
import RawLiveLog from '@/components/catalog/RawLiveLog';
import { parseProgress } from '@/lib/rawJobLog';
import { cn } from '@/lib/utils';

const LIVE_STATUSES = ['queued', 'running', 'cancelling'];
const POLL_MS = 2000;

// Real backend phases (customization_worker.py) mapped onto friendly labels --
// "installed"/"cancelled"/"failed" are terminal statuses, not shown here.
const PHASE_LABEL_KEY = {
  preparing_working_copy: 'cat.cs.phasePreparing',
  applying_local_filters: 'cat.cs.phaseFilters',
  scanning_nasa: 'cat.cs.phaseScanning',
  enriching_metadata: 'cat.cs.phaseMetadata',
  validating_working_copy: 'cat.cs.phaseValidating',
  installing_catalog: 'cat.cs.phaseInstalling',
};

// customization.py's own dimension names ("product_types", "processing_levels",
// "camera_prefixes", "processing_markers") don't match segment_explain.py's
// vocabulary (singular, borrowed from product_composition.py's own segments:
// "product_type", "suffix", "camera_prefix", "processing_marker") -- MMM
// cameras' "processing level" IS a suffix code (DRCL/DRCX/DRLX/DRXX), just
// under a customization-specific name, so map rather than duplicate.
const EXPLAIN_DIMENSION = {
  product_types: 'product_type',
  processing_levels: 'suffix',
  camera_prefixes: 'camera_prefix',
  processing_markers: 'processing_marker',
};

// Same coarse "about this long" estimate as the legacy Streamlit dialog
// (app.py's own format_duration()/apply-button handler): pure local removals
// are cheap (no NASA round-trip, flat 90s baseline); any addition needs a
// live scan, which scales with how many Sols and how many cameras need one.
// Kept a range (0.75x-1.5x) rather than a single number since it's a rough
// guess, not a measured duration.
function formatDuration(seconds) {
  if (seconds == null) return '—';
  const value = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(value / 3600);
  const remainder = value % 3600;
  const minutes = value ? Math.max(1, Math.floor(remainder / 60)) : 0;
  return hours ? `${hours} h ${minutes} min` : `${minutes} min`;
}

function estimateDuration(stagedEntries, solStart, solEnd) {
  const cameras = new Set(stagedEntries.map((e) => e.cam));
  const remoteCameras = Array.from(cameras).filter((cam) => stagedEntries.some((e) => e.cam === cam && e.willAdd)).length;
  const solCount = solEnd - solStart + 1;
  const seconds = remoteCameras === 0 ? 90 : Math.max(60, solCount * remoteCameras * 3);
  return `${formatDuration(seconds * 0.75)}–${formatDuration(seconds * 1.5)}`;
}

// PDS-only, matching the real backend: `jobs.start_pds_customization_job` has
// no RAW counterpart (RAW isn't scanned with camera_rules.json-style filters).
export default function CatalogPersonalize({ kind }) {
  const { t, settings } = useAppSettings();
  const [options, setOptions] = useState(null);
  const [original, setOriginal] = useState(null);
  const [selection, setSelection] = useState({});
  const [camera, setCamera] = useState(null);
  const [solStart, setSolStart] = useState(0);
  const [solEnd, setSolEnd] = useState(0);
  const [loading, setLoading] = useState(true);
  const [job, setJob] = useState(null);
  const [logText, setLogText] = useState('');
  const [error, setError] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const pollRef = useRef(null);

  useEffect(() => {
    if (kind !== 'pds') {
      setLoading(false);
      return;
    }
    setLoading(true);
    Promise.all([getCustomizationOptions(), getCustomizationCurrent(), getStatus('pds')])
      .then(([opts, current, status]) => {
        setOptions(opts);
        const seeded = {};
        Object.keys(opts).forEach((cam) => {
          seeded[cam] = { ...(current[cam] || {}) };
        });
        setOriginal(seeded);
        setSelection(JSON.parse(JSON.stringify(seeded)));
        setCamera(Object.keys(opts)[0] || null);
        setSolEnd(status.sol_max || 0);
      })
      .finally(() => setLoading(false));
    // A customization run is a detached subprocess (catalog_manager/jobs.py):
    // it keeps going server-side even if this tab unmounts (navigate away,
    // close the app). Without this, coming back would show no job at all --
    // "in background" only holds if the UI can still find and tail it.
    getLatestJob('pds', 'catalog_customization')
      .then((existing) => {
        if (existing && LIVE_STATUSES.includes(existing.status)) {
          setJob(existing);
          getJobLog(existing.job_id).then((r) => setLogText(r.log)).catch(() => {});
        }
      })
      .catch(() => {});
  }, [kind]);

  // Poll the running job's status + its worker's live log text every 2s,
  // mirroring CatalogUpdates.jsx's own polling for the same job architecture.
  useEffect(() => {
    if (!job || !LIVE_STATUSES.includes(job.status)) {
      if (pollRef.current) clearInterval(pollRef.current);
      return undefined;
    }
    pollRef.current = setInterval(() => {
      getJob(job.job_id).then(setJob).catch(() => {});
      getJobLog(job.job_id).then((r) => setLogText(r.log)).catch(() => {});
    }, POLL_MS);
    return () => clearInterval(pollRef.current);
  }, [job?.job_id, job?.status]);

  const isSelected = (primary, secondary) => (selection[camera]?.[primary] || []).includes(secondary);

  const toggle = (primary, secondary) => {
    setSelection((prev) => {
      const camSel = { ...(prev[camera] || {}) };
      const current = new Set(camSel[primary] || []);
      if (current.has(secondary)) current.delete(secondary);
      else current.add(secondary);
      camSel[primary] = Array.from(current);
      return { ...prev, [camera]: camSel };
    });
  };

  const stagedEntries = useMemo(() => {
    if (!options) return [];
    const entries = [];
    Object.keys(options).forEach((cam) => {
      const before = original?.[cam] || {};
      const after = selection[cam] || {};
      const primaries = new Set([...Object.keys(before), ...Object.keys(after)]);
      primaries.forEach((primary) => {
        const beforeSet = new Set(before[primary] || []);
        const afterSet = new Set(after[primary] || []);
        beforeSet.forEach((sec) => {
          if (!afterSet.has(sec)) entries.push({ key: `${cam}:${primary}:${sec}:-`, cam, primary, code: sec, willAdd: false });
        });
        afterSet.forEach((sec) => {
          if (!beforeSet.has(sec)) entries.push({ key: `${cam}:${primary}:${sec}:+`, cam, primary, code: sec, willAdd: true });
        });
      });
    });
    return entries;
  }, [options, original, selection]);

  const discard = () => setSelection(JSON.parse(JSON.stringify(original)));

  const buildChanges = () => {
    // Send every camera that changed, with its FULL desired selection (the
    // backend needs the complete combination set per camera, not just a diff).
    const changedCameras = new Set(stagedEntries.map((e) => e.cam));
    const changes = {};
    changedCameras.forEach((cam) => {
      const camSel = selection[cam] || {};
      const cleaned = Object.fromEntries(Object.entries(camSel).filter(([, values]) => values.length > 0));
      if (Object.keys(cleaned).length) changes[cam] = cleaned;
    });
    return changes;
  };

  const handleApply = () => {
    setError(null);
    if (!Object.keys(buildChanges()).length) return;
    setConfirmOpen(true);
  };

  const handleConfirmedApply = () => {
    setConfirmOpen(false);
    const changes = buildChanges();
    if (!Object.keys(changes).length) return;
    startCustomization(changes, solStart, solEnd)
      .then(setJob)
      .catch((err) => setError(err.message || String(err)));
  };

  const handleStop = () => {
    if (job) cancelJob(job.job_id);
  };

  if (kind !== 'pds') {
    return (
      <Section icon={SlidersHorizontal} eyebrow={t('cat.cs.title')} description={t('cat.cs.desc')}>
        <Panel className="max-w-2xl">
          <PanelBody className="text-xs text-muted-foreground">RAW Archive · {t('cat.cs.needsSearch')}</PanelBody>
        </Panel>
      </Section>
    );
  }

  if (loading || !options) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t('cat.ov.loading')}
      </div>
    );
  }

  const cameras = Object.keys(options);
  const config = options[camera] || { primary: [], secondary: [] };
  const running = job && LIVE_STATUSES.includes(job.status);
  const phaseKey = job?.phase ? PHASE_LABEL_KEY[job.phase] : null;
  const progress = running ? parseProgress(logText, job) : null;

  return (
    <Section icon={SlidersHorizontal} eyebrow={t('cat.cs.title')} description={t('cat.cs.desc')}>
      <div className="grid gap-4 lg:grid-cols-[220px_1fr_300px]">
        <Panel>
          <PanelBody className="space-y-1 p-2">
            {cameras.map((cam) => (
              <button
                key={cam}
                type="button"
                onClick={() => setCamera(cam)}
                className={cn(
                  'flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors',
                  camera === cam ? 'bg-primary/10 text-foreground' : 'text-muted-foreground hover:bg-accent/40 hover:text-foreground'
                )}
              >
                {CAMERA_LABELS[cam] || cam}
              </button>
            ))}
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader>
            <PanelTitle>
              {t('cat.cs.available')} · {CAMERA_LABELS[camera] || camera}
            </PanelTitle>
          </PanelHeader>
          <PanelBody scroll className="max-h-[36rem] space-y-5">
            {config.primary.map((primary) => (
              <div key={primary} className="space-y-2">
                <CodeTooltip
                  dimension={EXPLAIN_DIMENSION[config.primary_dimension]}
                  code={primary}
                  lang={settings.language}
                  camera={camera}
                  className="text-sm"
                />
                <div className="grid grid-cols-2 gap-x-5 gap-y-2 pl-1 sm:grid-cols-3 xl:grid-cols-4">
                  {config.secondary.map((secondary) => (
                    <label key={secondary} className="flex cursor-pointer items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={isSelected(primary, secondary)}
                        onChange={() => toggle(primary, secondary)}
                        className="h-4 w-4 shrink-0 rounded border-border accent-current text-primary"
                      />
                      <CodeTooltip
                        dimension={EXPLAIN_DIMENSION[config.secondary_dimension]}
                        code={secondary}
                        lang={settings.language}
                        camera={camera}
                        className="text-[13px]"
                      />
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader>
            <PanelTitle>{t('cat.cs.staged')}</PanelTitle>
          </PanelHeader>
          <PanelBody scroll className="max-h-72">
            {stagedEntries.length === 0 ? (
              <PanelEmpty icon={Check}>{t('cat.cs.noStaged')}</PanelEmpty>
            ) : (
              <ul className="space-y-1.5">
                {stagedEntries.map((e) => (
                  <li key={e.key} className="flex items-center gap-2 text-xs">
                    {e.willAdd ? (
                      <Plus className="h-3 w-3 shrink-0 text-emerald-500" aria-hidden="true" />
                    ) : (
                      <Minus className="h-3 w-3 shrink-0 text-destructive" aria-hidden="true" />
                    )}
                    <span className="truncate text-muted-foreground">
                      {CAMERA_LABELS[e.cam] || e.cam} · <span className="font-mono text-foreground">{e.primary}/{e.code}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </PanelBody>
          {stagedEntries.length > 0 && !running && (
            <PanelFooter className="space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <FieldLabel className="mb-1">{t('download.solStart')}</FieldLabel>
                  <Input type="number" value={solStart} onChange={(e) => setSolStart(Number(e.target.value))} className="h-7 font-mono text-xs" />
                </div>
                <div>
                  <FieldLabel className="mb-1">{t('download.solEnd')}</FieldLabel>
                  <Input type="number" value={solEnd} onChange={(e) => setSolEnd(Number(e.target.value))} className="h-7 font-mono text-xs" />
                </div>
              </div>
              <p className="text-[11px] leading-relaxed text-muted-foreground">{t('cat.cs.needsSearch')}</p>
              {error && <p className="text-[11px] text-destructive">{error}</p>}
              <div className="flex gap-2">
                <Button size="sm" className="flex-1" onClick={handleApply}>
                  {t('cat.cs.apply')}
                </Button>
                <Button size="sm" variant="ghost" onClick={discard} aria-label={t('cat.cs.discard')}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </PanelFooter>
          )}
          {running && (
            <PanelFooter className="flex flex-col items-stretch gap-2">
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
              <Button
                size="sm"
                variant="destructive"
                className="w-full"
                onClick={handleStop}
                disabled={job.status === 'cancelling'}
              >
                <Square className="h-3.5 w-3.5" />
                {t('cat.cs.stop')}
              </Button>
            </PanelFooter>
          )}
          {job && !running && job.status === 'completed' && (
            <PanelFooter>
              <p className="text-xs text-emerald-600 dark:text-emerald-400">
                +{Object.values(job.added_by_camera || {}).reduce((a, b) => a + b, 0)} / -
                {Object.values(job.removed_by_camera || {}).reduce((a, b) => a + b, 0)}
              </p>
            </PanelFooter>
          )}
        </Panel>
      </div>

      {job && (
        <RawLiveLog
          logText={logText}
          isLive={running}
          onClear={() => setLogText('')}
          className="max-w-2xl"
        />
      )}

      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={t('cat.cs.confirmTitle')}
        icon={SlidersHorizontal}
        footer={
          <>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              {t('confirm.cancel')}
            </Button>
            <Button onClick={handleConfirmedApply}>{t('confirm.continue')}</Button>
          </>
        }
      >
        <p className="text-sm leading-relaxed text-muted-foreground">
          {t('cat.cs.confirmText', { estimate: estimateDuration(stagedEntries, solStart, solEnd) })}
        </p>
      </Modal>
    </Section>
  );
}
