import React, { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Eyebrow } from '@/components/ui/section';
import ToggleChip from '@/components/ui/toggle-chip';
import { Search, Loader2, Camera, Layers, Hash, FolderTree, SlidersHorizontal } from 'lucide-react';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { CAMERA_GROUPS } from '@/lib/mslApi';

const CATALOGS = ['PDS', 'RAW', 'both'];
const ORGS = ['camera', 'sol', 'both'];

// One field = one micro-label + its control(s) + an optional hint. Every field
// in the form uses the same three steps, so the panel scans as a single column
// instead of six differently-sized blocks.
function Field({ icon: Icon, label, children, error }) {
  return (
    <div className="space-y-3">
      <Eyebrow icon={Icon}>{label}</Eyebrow>
      {children}
      {error && <p className="text-[11px] leading-snug text-destructive">{error}</p>}
    </div>
  );
}

function NumberInput({ value, onChange, hint, ...props }) {
  return (
    <div className="space-y-1">
      <Input
        type="number"
        inputMode="numeric"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-8 font-mono text-sm tabular-nums"
        {...props}
      />
      <span className="block text-[11px] leading-tight text-muted-foreground">{hint}</span>
    </div>
  );
}

export default function DownloadPreparation({ onApply, isSearching }) {
  const { t } = useAppSettings();
  const [solStart, setSolStart] = useState(3347);
  const [solEnd, setSolEnd] = useState(3351);
  const [cameras, setCameras] = useState(() => CAMERA_GROUPS.map((c) => c.id));
  const [catalog, setCatalog] = useState('both');
  const [minSize, setMinSize] = useState(0);
  const [maxImages, setMaxImages] = useState(50);
  const [organization, setOrganization] = useState('both');

  const toggleCamera = (id) =>
    setCameras((prev) => (prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]));

  const allCameras = cameras.length === CAMERA_GROUPS.length;
  const toggleAll = () => setCameras(allCameras ? [] : CAMERA_GROUPS.map((c) => c.id));

  const invalidRange = solEnd < solStart;
  const noCameras = cameras.length === 0;
  const canApply = !isSearching && !invalidRange && !noCameras;

  const handleApply = () => {
    if (!canApply) return;
    onApply({ solStart, solEnd, cameras, catalog, minSize, maxImages, organization });
  };

  const catalogDescription =
    catalog === 'PDS'
      ? t('download.catalogPDS_desc')
      : catalog === 'RAW'
        ? t('download.catalogRAW_desc')
        : `${t('download.catalogPDS_desc')} · ${t('download.catalogRAW_desc')}`;

  return (
    <div className="space-y-11 p-5">
      <h2 className="font-heading text-[13px] font-semibold tracking-tight">
        {t('download.title')}
      </h2>

      <Field
        icon={Hash}
        label={t('download.solRange')}
        error={invalidRange ? t('download.errRange') : null}
      >
        <div className="grid grid-cols-2 gap-2">
          <NumberInput value={solStart} onChange={setSolStart} min={0} hint={t('download.solStart')} />
          <NumberInput value={solEnd} onChange={setSolEnd} min={0} hint={t('download.solEnd')} />
        </div>
      </Field>

      <Field
        icon={Camera}
        label={t('download.cameras')}
        error={noCameras ? t('download.errCameras') : null}
      >
        <div className="flex flex-wrap gap-1.5">
          <ToggleChip active={allCameras} onClick={toggleAll} className="px-2.5 py-1 text-xs">
            {t('common.all')}
          </ToggleChip>
          {CAMERA_GROUPS.map((c) => (
            <ToggleChip
              key={c.id}
              active={cameras.includes(c.id)}
              onClick={() => toggleCamera(c.id)}
              className="px-2.5 py-1 text-xs"
            >
              {c.label}
            </ToggleChip>
          ))}
        </div>
      </Field>

      <Field icon={Layers} label={t('download.catalogs')}>
        <div className="grid grid-cols-3 gap-1.5">
          {CATALOGS.map((c) => (
            <ToggleChip
              key={c}
              active={catalog === c}
              onClick={() => setCatalog(c)}
              className="px-2 py-1 text-xs"
            >
              {c === 'both' ? t('download.catalogBoth') : c}
            </ToggleChip>
          ))}
        </div>
        <p className="text-[11px] leading-relaxed text-muted-foreground">{catalogDescription}</p>
      </Field>

      <Field icon={SlidersHorizontal} label={t('download.limits')}>
        <div className="grid grid-cols-2 gap-2">
          <NumberInput value={minSize} onChange={setMinSize} min={0} hint={t('download.minSize')} />
          <NumberInput value={maxImages} onChange={setMaxImages} min={0} hint={t('download.maxImages')} />
        </div>
      </Field>

      <Field icon={FolderTree} label={t('download.organization')}>
        <div className="grid grid-cols-3 gap-1.5">
          {ORGS.map((o) => (
            <ToggleChip
              key={o}
              active={organization === o}
              onClick={() => setOrganization(o)}
              className="px-2 py-1 text-xs"
            >
              {o === 'camera'
                ? t('download.orgCamera')
                : o === 'sol'
                  ? t('download.orgSol')
                  : t('download.orgBoth')}
            </ToggleChip>
          ))}
        </div>
      </Field>

      <Button
        className="h-auto min-h-9 w-full whitespace-normal py-2.5 text-center leading-snug"
        onClick={handleApply}
        disabled={!canApply}
      >
        {isSearching ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('download.applying')}
          </>
        ) : (
          <>
            <Search className="h-4 w-4" />
            {t('download.apply')}
          </>
        )}
      </Button>
    </div>
  );
}
