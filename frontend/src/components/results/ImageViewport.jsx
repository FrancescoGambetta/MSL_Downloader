import React from 'react';
import { Telescope, Eye } from 'lucide-react';
import { Panel, PanelHeader, PanelTitle, PanelBody, PanelEmpty } from '@/components/ui/panel';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { cn } from '@/lib/utils';

export default function ImageViewport({ image, className }) {
  const { t } = useAppSettings();

  return (
    <Panel className={cn('h-[22rem] md:h-[26rem] xl:h-full', className)}>
      <PanelHeader>
        <PanelTitle icon={Eye}>{t('viewport.title')}</PanelTitle>
        {image && (
          <span className="shrink-0 truncate font-mono text-xs text-muted-foreground">
            {image.product_id}
          </span>
        )}
      </PanelHeader>

      <PanelBody className="flex items-center justify-center bg-muted/30 p-3">
        {image ? (
          <img
            src={image.img_src}
            alt={image.product_id}
            decoding="async"
            className="max-h-full max-w-full rounded-lg object-contain shadow-lg"
          />
        ) : (
          <PanelEmpty icon={Telescope}>{t('viewport.empty')}</PanelEmpty>
        )}
      </PanelBody>
    </Panel>
  );
}
