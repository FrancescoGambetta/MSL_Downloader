import React from 'react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Sheet } from '@/components/ui/modal';
import ToggleChip from '@/components/ui/toggle-chip';
import { Sun, Moon, Globe, Palette, FolderOpen, Type, Settings } from 'lucide-react';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { LANGUAGES } from '@/lib/translations';
import { cn } from '@/lib/utils';

function Section({ icon: Icon, title, description = null, children }) {
  return (
    <section className="space-y-4">
      <div>
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Icon className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          {title}
        </h3>
        {description && <p className="mt-1 text-xs text-muted-foreground">{description}</p>}
      </div>
      {children}
    </section>
  );
}

function OptionCard({ active, onClick, className = '', children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'rounded-xl border p-3 text-left transition-all duration-150',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card',
        active
          ? 'border-primary bg-primary/5 ring-2 ring-primary/25'
          : 'border-border hover:border-primary/40 hover:bg-accent/50',
        className
      )}
    >
      {children}
    </button>
  );
}

export default function SettingsPanel({ open, onClose }) {
  const { settings, update, t, palettes, fonts } = useAppSettings();

  return (
    <Sheet open={open} onClose={onClose} title={t('settings.title')} icon={Settings}>
      <div className="space-y-8">
        <Section icon={Palette} title={t('settings.appearance')} description={t('settings.appearanceDesc')}>
          <div className="space-y-2.5">
            <Label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Globe className="h-3.5 w-3.5" aria-hidden="true" />
              {t('settings.language')}
            </Label>
            <div className="flex flex-wrap gap-2">
              {LANGUAGES.map((l) => (
                <ToggleChip
                  key={l.code}
                  active={settings.language === l.code}
                  onClick={() => update({ language: l.code })}
                  className="text-xs"
                >
                  {l.label}
                </ToggleChip>
              ))}
            </div>
          </div>

          <div className="space-y-2.5">
            <Label className="text-xs text-muted-foreground">{t('settings.mode')}</Label>
            <div className="flex gap-2">
              <ToggleChip
                active={settings.mode === 'light'}
                onClick={() => update({ mode: 'light' })}
                className="text-xs"
              >
                <Sun className="h-3.5 w-3.5" aria-hidden="true" />
                {t('settings.light')}
              </ToggleChip>
              <ToggleChip
                active={settings.mode === 'dark'}
                onClick={() => update({ mode: 'dark' })}
                className="text-xs"
              >
                <Moon className="h-3.5 w-3.5" aria-hidden="true" />
                {t('settings.dark')}
              </ToggleChip>
            </div>
          </div>

          <div className="space-y-2.5">
            <Label className="text-xs text-muted-foreground">{t('settings.theme')}</Label>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {palettes.map((p) => (
                <OptionCard
                  key={p.id}
                  active={settings.palette === p.id}
                  onClick={() => update({ palette: p.id })}
                  className="flex items-center gap-3"
                >
                  <span className="flex shrink-0 -space-x-1.5">
                    {p.colors.map((c) => (
                      <span
                        key={c}
                        className="h-4 w-4 rounded-full ring-1 ring-black/10"
                        style={{ background: c }}
                      />
                    ))}
                  </span>
                  <span className="truncate text-sm font-medium">{t(`palette.${p.id}`)}</span>
                </OptionCard>
              ))}
            </div>
          </div>
        </Section>

        <div className="h-px bg-border" />

        <Section icon={Type} title={t('settings.fonts')} description={t('settings.fontsDesc')}>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {fonts.map((f) => (
              <OptionCard
                key={f.id}
                active={settings.font === f.id}
                onClick={() => update({ font: f.id })}
              >
                <span style={{ fontFamily: f.stack }} className="block text-lg leading-tight">
                  {f.label}
                </span>
                <span className="mt-1 block truncate text-xs text-muted-foreground">{f.family}</span>
              </OptionCard>
            ))}
          </div>
        </Section>

        <div className="h-px bg-border" />

        <Section icon={FolderOpen} title={t('settings.output')} description={t('settings.outputDesc')}>
          <Input
            id="settings-output"
            value={settings.outputFolder}
            onChange={(e) => update({ outputFolder: e.target.value })}
            placeholder={t('settings.outputPlaceholder')}
            className="h-10 font-mono text-sm"
          />
        </Section>
      </div>
    </Sheet>
  );
}
