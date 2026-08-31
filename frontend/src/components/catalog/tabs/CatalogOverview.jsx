import React, { useEffect, useState } from 'react';
import { ArrowRight, Boxes, Loader2 } from 'lucide-react';
import { Section } from '@/components/ui/section';
import { StatTile, Meter } from '@/components/ui/metric';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { getStatusFull, getCachedStatusFull, CAMERA_LABELS } from '@/lib/catalogManagerApi';

function formatBytes(value) {
  let size = Number(value || 0);
  for (const unit of ['B', 'KB', 'MB', 'GB']) {
    if (size < 1024 || unit === 'GB') return `${size.toFixed(1)} ${unit}`;
    size /= 1024;
  }
  return `${size.toFixed(1)} GB`;
}

export default function CatalogOverview({ kind }) {
  const { t } = useAppSettings();
  // Lazy-initialised from the cross-mount cache (see getCachedStatusFull's
  // docstring): this component gets fully unmounted/remounted on every tab
  // switch, so without this every visit -- even a second one, seconds later
  // -- would flash a blank spinner while re-fetching data nothing changed.
  // When a cached entry exists we paint it immediately and treat this as a
  // background refresh instead of an initial load.
  const [status, setStatus] = useState(() => getCachedStatusFull(kind));
  const [loading, setLoading] = useState(() => !getCachedStatusFull(kind));
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const cached = getCachedStatusFull(kind);
    setStatus(cached);
    setLoading(!cached);
    setError(null);
    getStatusFull(kind)
      .then((data) => {
        if (!cancelled) setStatus(data);
      })
      .catch((err) => {
        // A stale cached view is still more useful than an error banner --
        // only surface the error when we had nothing to show already.
        if (!cancelled && !cached) setError(err.message || String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [kind]);

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t('cat.ov.loading')}
      </div>
    );
  }

  if (error || !status || !status.exists) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        {error || 'Catalogo non installato.'}
      </div>
    );
  }

  const localSol = status.sol_max ?? 0;
  const serverSol = status.remote_latest_sol;
  const hasRemote = serverSol !== null && serverSol !== undefined;
  const newSols = hasRemote ? Math.max(0, serverSol - localSol) : 0;
  const upToDate = hasRemote ? status.update_available === false : null;
  const distribution = Object.entries(status.cameras || {})
    .map(([camera, count]) => ({ camera: CAMERA_LABELS[camera] || camera, count }))
    .sort((a, b) => b.count - a.count);
  const topCount = distribution[0]?.count || 1;

  return (
    <div className="space-y-8">
      <Section
        eyebrow={t('cat.ov.eyebrow')}
        title={`${t('cat.ov.title')} · ${kind === 'raw' ? 'RAW Archive' : 'PDS'}`}
        description={t('cat.ov.compare')}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile label={t('cat.ov.localSol')} value={localSol.toLocaleString()} hint={t('cat.ov.installed')} />
          <StatTile
            label={t('cat.ov.serverSol')}
            value={hasRemote ? serverSol.toLocaleString() : '—'}
            hint={hasRemote ? t('cat.ov.nasaArchive') : t('cat.ov.notChecked')}
          />
          <StatTile
            label={t('cat.ov.status')}
            value={upToDate === null ? t('cat.ov.notChecked') : upToDate ? t('cat.ov.upToDate') : t('cat.ov.updateAvailable')}
            dot
            tone={upToDate === null ? 'muted' : upToDate ? 'positive' : 'warning'}
          />
          <StatTile
            label={t('cat.ov.newSols')}
            value={hasRemote ? `+${newSols}` : '—'}
            hint={t('cat.ov.newSolsHint')}
            tone={!hasRemote || upToDate ? 'muted' : 'accent'}
          />
        </div>
      </Section>

      <Section icon={Boxes} eyebrow={t('cat.ov.detailsTitle')}>
        <div className="grid gap-3 lg:grid-cols-3">
          <StatTile label={t('cat.ov.totalProducts')} value={(status.rows || 0).toLocaleString()} />
          <StatTile label={t('cat.ov.solRange')} value={`${status.sol_min ?? 0}–${localSol.toLocaleString()}`} />
          <StatTile label={t('cat.ov.size')} value={formatBytes(status.size_bytes)} />
        </div>
      </Section>

      <Section icon={ArrowRight} eyebrow={t('cat.ov.distribution')}>
        <div className="max-w-2xl space-y-3 rounded-lg border border-border bg-card p-4">
          {distribution.map((d) => (
            <Meter key={d.camera} label={d.camera} value={d.count} max={topCount} />
          ))}
        </div>
      </Section>
    </div>
  );
}
