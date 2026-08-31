import React from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Panel, PanelHeader, PanelTitle, PanelBody, PanelEmpty } from '@/components/ui/panel';
import { ImageOff, CheckCircle2, SkipForward, AlertTriangle, Images, Trash2 } from 'lucide-react';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { cn } from '@/lib/utils';

const STATUS_ICON = {
  downloaded: { icon: CheckCircle2, cls: 'text-emerald-400' },
  skipped: { icon: SkipForward, cls: 'text-white/70' },
  error: { icon: AlertTriangle, cls: 'text-red-400' },
};

export default function ImageResults({ images, selectedImage, onSelect, onClear, className }) {
  const { t } = useAppSettings();

  return (
    <Panel className={cn('h-[26rem] md:h-[30rem] xl:h-full', className)}>
      <PanelHeader>
        <PanelTitle icon={Images}>{t('results.title')}</PanelTitle>
        <div className="flex shrink-0 items-center gap-1.5">
          {images.length > 0 && (
            <Badge variant="secondary" className="font-mono text-[11px] tabular-nums">
              {images.length} {t('results.count')}
            </Badge>
          )}
          {images.length > 0 && onClear && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={onClear}
              title={t('results.clear')}
              aria-label={t('results.clear')}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </PanelHeader>

      <PanelBody scroll className="px-3 py-3 sm:px-3.5">
        {images.length === 0 ? (
          <PanelEmpty icon={ImageOff}>{t('results.empty')}</PanelEmpty>
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(7rem,1fr))] gap-2.5">
            {images.map((img) => {
              const meta = STATUS_ICON[img.status] || STATUS_ICON.downloaded;
              const Icon = meta.icon;
              const active = selectedImage?.id === img.id;
              return (
                <button
                  key={img.id}
                  type="button"
                  onClick={() => onSelect(img)}
                  aria-pressed={active}
                  title={img.product_id}
                  className={cn(
                    'group relative aspect-square overflow-hidden rounded-lg border transition-colors duration-200',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card',
                    active
                      ? 'border-primary ring-2 ring-primary/30'
                      : 'border-border hover:border-primary/40'
                  )}
                >
                  <img
                    src={img.img_src}
                    alt={img.product_id}
                    loading="lazy"
                    decoding="async"
                    className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
                  />
                  <span className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/75 via-black/10 to-transparent" />
                  <span className="pointer-events-none absolute inset-x-1.5 bottom-1.5 flex items-center justify-between gap-1">
                    <span className="truncate font-mono text-[10px] text-white drop-shadow">
                      {img.camera}
                    </span>
                    <Icon className={cn('h-3 w-3 shrink-0 drop-shadow', meta.cls)} aria-hidden="true" />
                  </span>
                  <span className="pointer-events-none absolute right-1.5 top-1.5 rounded-md bg-black/50 px-1.5 py-0.5 font-mono text-[10px] text-white/90 backdrop-blur-sm">
                    {img.sol}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </PanelBody>
    </Panel>
  );
}
