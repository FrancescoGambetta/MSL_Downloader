import React, { useEffect, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Panel, PanelHeader, PanelTitle, PanelBody, PanelEmpty } from '@/components/ui/panel';
import { Info, FileQuestion, ChevronDown } from 'lucide-react';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { fetchRealMeta } from '@/lib/mslApi';
import { cn } from '@/lib/utils';

function AdvancedGroup({ title, entries }) {
  if (!entries.length) return null;
  return (
    <div className="pt-2 first:pt-0">
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-primary">{title}</p>
      {entries.map(([label, value]) => (
        <Field key={label} label={label} value={value == null ? null : String(value)} mono />
      ))}
    </div>
  );
}

function Field({ label, value, mono = false }) {
  return (
    <div className="border-b border-border/70 py-2 last:border-0">
      <p className="mb-0.5 text-[10px] font-medium uppercase tracking-[0.1em] text-muted-foreground">
        {label}
      </p>
      <p className={cn('break-all text-xs', mono && 'font-mono')}>{value || '—'}</p>
    </div>
  );
}

export default function MetadataPanel({ image, className }) {
  const { t } = useAppSettings();
  // Real post-processing metadata (the actual .meta.json written after the
  // engine ran), matching what the Streamlit app's metadata panel shows --
  // this used to just reuse the catalog-search-time record instead, which
  // could disagree with (or simply lack) what the engine actually wrote:
  // img_url and errors weren't shown at all. Falls back to the catalog
  // record's own fields (unavailable/older records) when there's no job_id
  // yet or the real file can't be found.
  const [real, setReal] = useState(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setReal(null);
    setShowAdvanced(false);
    if (image?.job_id) {
      fetchRealMeta(image.job_id, image.product_id, image.output_root).then((meta) => {
        if (!cancelled) setReal(meta);
      });
    }
    return () => {
      cancelled = true;
    };
  }, [image?.job_id, image?.product_id, image?.output_root]);

  return (
    // At `md` it shares the row with the viewport, so their heights match.
    <Panel className={cn('h-[22rem] md:h-[26rem] xl:h-full', className)}>
      <PanelHeader>
        <PanelTitle icon={Info}>{t('metadata.title')}</PanelTitle>
        {image && (
          <Badge
            variant={image.status === 'error' ? 'destructive' : 'secondary'}
            className="shrink-0 capitalize"
          >
            {image.status}
          </Badge>
        )}
      </PanelHeader>

      <PanelBody scroll>
        {!image ? (
          <PanelEmpty icon={FileQuestion}>{t('metadata.noSelection')}</PanelEmpty>
        ) : (
          <div>
            <Field label={t('metadata.productId')} value={real?.product_id || image.product_id} mono />
            <Field
              label={t('metadata.camera')}
              value={`${image.camera} (${real?.instrument_name || real?.instrument_id || image.instrument})`}
            />
            <Field label={t('metadata.sol')} value={real?.sol ?? image.sol} />
            <Field label={t('metadata.earthDate')} value={image.earth_date} />
            <Field label={t('metadata.site')} value={real?.site ?? image.site} />
            <Field label={t('metadata.drive')} value={real?.drive ?? image.drive} />
            <Field label={t('metadata.pose')} value={real?.pose ?? image.pose} />
            <Field label={t('metadata.source')} value={image.source_catalog} />
            <Field
              label={t('metadata.size')}
              value={image.file_size_kb ? `${image.file_size_kb} KB` : '—'}
            />
            {(real?.img_url || image.img_url) && (
              <Field label="img_url" value={real?.img_url || image.img_url} mono />
            )}
            <Field
              label={t('metadata.jpgPath')}
              value={real?.jpg_path || `${image.output_path}${image.product_id}.jpg`}
              mono
            />
            <Field label={t('metadata.metaPath')} value={real?.meta_json_path || image.metadata_path} mono />
            {image.warnings && <Field label={t('metadata.warnings')} value={image.warnings} />}
            {real?.warnings?.length > 0 && (
              <Field label={t('metadata.warnings')} value={real.warnings.join('; ')} />
            )}
            {real?.errors?.length > 0 && <Field label="errors" value={real.errors.join('; ')} />}

            {real?.advanced && (
              <div className="mt-1 border-t border-border/70 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAdvanced((v) => !v)}
                  aria-expanded={showAdvanced}
                  className="flex w-full items-center justify-between py-1 text-[11px] font-medium uppercase tracking-[0.1em] text-muted-foreground transition-colors hover:text-foreground"
                >
                  {t('metadata.advanced')}
                  <ChevronDown
                    className={cn('h-3.5 w-3.5 shrink-0 transition-transform', showAdvanced && 'rotate-180')}
                    aria-hidden="true"
                  />
                </button>
                {showAdvanced && (
                  <div className="divide-y divide-border/40">
                    {real.advanced.gps && (
                      <AdvancedGroup
                        title={t('metadata.gps')}
                        entries={Object.entries(real.advanced.gps)}
                      />
                    )}
                    {real.advanced.orientation && (
                      <AdvancedGroup
                        title={t('metadata.orientation')}
                        entries={Object.entries(real.advanced.orientation)}
                      />
                    )}
                    {real.advanced.exif && (
                      <AdvancedGroup title={t('metadata.exif')} entries={Object.entries(real.advanced.exif)} />
                    )}
                    {real.advanced.post_processing && (
                      <AdvancedGroup
                        title={t('metadata.postProcessing')}
                        entries={Object.entries(real.advanced.post_processing)}
                      />
                    )}
                    {real.advanced.alpha_pair && (
                      <AdvancedGroup
                        title={t('metadata.alphaPair')}
                        entries={Object.entries(real.advanced.alpha_pair).map(([k, v]) => [
                          k,
                          k === 'mask_coverage' && typeof v === 'number' ? `${(v * 100).toFixed(1)}%` : v,
                        ])}
                      />
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </PanelBody>
    </Panel>
  );
}
