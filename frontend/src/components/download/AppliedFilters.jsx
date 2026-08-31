import React from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Panel, PanelHeader, PanelTitle, PanelBody, PanelFooter } from '@/components/ui/panel';
import { DataRow } from '@/components/ui/metric';
import { Play, Square, Filter, Hash, Camera, Layers, Maximize2, FolderTree } from 'lucide-react';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { cn } from '@/lib/utils';

export default function AppliedFilters({ appliedFilters, isRunning, onStart, onStop, className }) {
  const { t } = useAppSettings();
  const f = appliedFilters;

  const organizationLabel = (value) =>
    value === 'camera' ? t('download.orgCamera') : value === 'sol' ? t('download.orgSol') : t('download.orgBoth');

  return (
    <Panel className={cn('min-h-[17rem]', className)}>
      <PanelHeader>
        <PanelTitle icon={Filter}>{t('filters.title')}</PanelTitle>
        {f && (
          <Badge variant="secondary" className="shrink-0 font-mono text-[11px] tabular-nums">
            {f.afterFilters} {t('filters.found')}
          </Badge>
        )}
      </PanelHeader>

      <PanelBody scroll>
        {!f ? (
          <div className="flex h-full items-center justify-center py-6">
            <p className="max-w-[28ch] text-center text-xs leading-relaxed text-muted-foreground">
              {t('filters.none')}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-border/70">
            <DataRow icon={Hash} label={t('filters.sol')} value={`${f.solStart} – ${f.solEnd}`} />
            <DataRow icon={Camera} label={t('filters.cameras')} value={f.cameras.join(', ')} mono={false} />
            <DataRow
              icon={Layers}
              label={t('filters.catalogs')}
              value={f.catalog === 'both' ? t('download.catalogBoth') : f.catalog}
              mono={false}
            />
            <DataRow icon={Maximize2} label={t('filters.minSize')} value={`${f.minSize} KB`} />
            <DataRow icon={Maximize2} label={t('filters.maxImages')} value={f.maxImages > 0 ? f.maxImages : '∞'} />
            <DataRow
              icon={FolderTree}
              label={t('filters.organization')}
              value={organizationLabel(f.organization)}
              mono={false}
            />
          </div>
        )}
      </PanelBody>

      <PanelFooter>
        {isRunning ? (
          <Button variant="destructive" className="w-full" onClick={onStop}>
            <Square className="h-4 w-4" />
            {t('execution.stop')}
          </Button>
        ) : (
          <Button className="w-full" onClick={onStart} disabled={!f || f.afterFilters === 0}>
            <Play className="h-4 w-4" />
            {t('execution.start')}
          </Button>
        )}
      </PanelFooter>
    </Panel>
  );
}
