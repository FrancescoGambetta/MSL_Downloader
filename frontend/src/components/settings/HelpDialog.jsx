import React from 'react';
import { Button } from '@/components/ui/button';
import { Modal } from '@/components/ui/modal';
import { HelpCircle } from 'lucide-react';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { translateArray } from '@/lib/translations';

export default function HelpDialog({ open, onClose }) {
  const { t, settings } = useAppSettings();
  const steps = translateArray(settings.language, 'help.steps');

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('help.title')}
      icon={HelpCircle}
      size="lg"
      footer={<Button onClick={onClose}>{t('common.close')}</Button>}
    >
      <p className="mb-5 text-xs italic text-muted-foreground">{t('help.note')}</p>
      <ol className="space-y-3">
        {steps.map((step, i) => (
          <li key={step} className="flex items-start gap-3">
            <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary">
              {i + 1}
            </span>
            <span className="text-sm leading-relaxed">{step}</span>
          </li>
        ))}
      </ol>
    </Modal>
  );
}
