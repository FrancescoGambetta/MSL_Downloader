import React, { useEffect, useState } from 'react';
import { Layers, ChevronDown, Loader2 } from 'lucide-react';
import { Panel, PanelBody } from '@/components/ui/panel';
import { Section } from '@/components/ui/section';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { getComposition, CAMERA_LABELS, CAMERA_KEYS } from '@/lib/catalogManagerApi';
import CodeTooltip from '@/components/catalog/CodeTooltip';
import { cn } from '@/lib/utils';

// Real per-camera filename-segment inventory (product_composition.py), grouped
// by dimension (product_type, suffix, processing_marker, sample_type, ...) --
// these are the actual structural markers NASA's filenames carry, not a
// curated "product family" taxonomy, so they're shown as-is rather than
// forced into invented display names.

// product_composition.py returns one flat list per camera, sorted purely by
// raw count -- that buries the actual composition: a dimension where every
// product carries the same single code (file_format=IMG for 100% of a
// camera, say) has the highest count of all, so it floats to the top ahead
// of a dimension that genuinely varies (product_type split 70/30). Group by
// dimension here instead, and rank dimensions that actually vary above ones
// that don't, so the one flat count-sorted list an API-shaped response naturally
// produces reads instead as "here's what varies, here's what's fixed".
function groupSegments(segments, totalProducts) {
  const byDimension = new Map();
  for (const segment of segments) {
    if (!byDimension.has(segment.dimension)) byDimension.set(segment.dimension, []);
    byDimension.get(segment.dimension).push(segment);
  }
  const groups = Array.from(byDimension.entries()).map(([dimension, items]) => {
    const sorted = [...items].sort((a, b) => b.count - a.count);
    const topShare = totalProducts ? sorted[0].count / totalProducts : 1;
    const constant = sorted.length === 1 && topShare >= 0.999;
    return { dimension, items: sorted, constant, variety: sorted.length };
  });
  groups.sort((a, b) => {
    if (a.constant !== b.constant) return a.constant ? 1 : -1;
    return b.variety - a.variety;
  });
  return groups;
}

export default function CatalogComposition({ kind }) {
  const { t, settings } = useAppSettings();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(null);

  useEffect(() => {
    setLoading(true);
    getComposition(kind)
      .then((result) => {
        setData(result);
        const first = CAMERA_KEYS.find((c) => result[c]);
        setOpen(first || null);
      })
      .finally(() => setLoading(false));
  }, [kind]);

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t('cat.ov.loading')}
      </div>
    );
  }

  const cameras = CAMERA_KEYS.filter((c) => data?.[c]);

  return (
    <Section icon={Layers} eyebrow={t('cat.cp.title')} description={t('cat.cp.desc')}>
      <div className="max-w-2xl space-y-2.5">
        {cameras.map((camera) => {
          const entry = data[camera];
          const expanded = open === camera;

          return (
            <Panel key={camera}>
              <button
                type="button"
                onClick={() => setOpen(expanded ? null : camera)}
                aria-expanded={expanded}
                className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left transition-colors hover:bg-accent/30"
              >
                <span className="flex min-w-0 items-center gap-2.5">
                  <span className="text-[13px] font-semibold">{CAMERA_LABELS[camera] || camera}</span>
                  <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                    {entry.total_products.toLocaleString()}
                  </span>
                </span>
                <ChevronDown
                  className={cn('h-4 w-4 shrink-0 text-muted-foreground transition-transform', expanded && 'rotate-180')}
                  aria-hidden="true"
                />
              </button>

              {expanded && (
                <PanelBody className="border-t border-border pt-3">
                  {entry.segments.length === 0 ? (
                    <p className="py-2 text-xs text-muted-foreground">—</p>
                  ) : (
                    <div className="space-y-3">
                      {groupSegments(entry.segments, entry.total_products).map((group) => (
                        <div key={group.dimension}>
                          <p className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground/70">
                            {group.dimension.replace(/_/g, ' ')}
                            {group.constant && (
                              <span className="ml-1.5 normal-case italic text-muted-foreground/40">
                                ({t('cat.cp.constant')})
                              </span>
                            )}
                          </p>
                          <div className={cn('divide-y divide-border/70', group.constant && 'opacity-60')}>
                            {group.items.map((segment) => (
                              <div key={segment.code} className="flex items-center gap-3 py-1.5">
                                <CodeTooltip
                                  dimension={group.dimension}
                                  code={segment.code}
                                  lang={settings.language}
                                  camera={camera}
                                  className="w-16 shrink-0 text-[11px]"
                                />
                                <span className="ml-auto shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground">
                                  {segment.count.toLocaleString()}
                                  {entry.total_products > 0 && (
                                    <span className="ml-1.5 text-muted-foreground/50">
                                      ({Math.round((segment.count / entry.total_products) * 100)}%)
                                    </span>
                                  )}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </PanelBody>
              )}
            </Panel>
          );
        })}
      </div>
    </Section>
  );
}
