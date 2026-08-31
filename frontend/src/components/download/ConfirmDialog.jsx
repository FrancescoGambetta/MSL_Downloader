import React from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Modal } from '@/components/ui/modal';
import { AlertTriangle } from 'lucide-react';
import { useAppSettings } from '@/lib/AppSettingsContext';

export default function ConfirmDialog({ open, count, limit, setLimit, onCancel, onConfirm }) {
  const { t } = useAppSettings();

  // Asking for more than were found would silently download all of them, so
  // the value is clamped to the actual result count.
  const handleLimitChange = (raw) => {
    if (raw === '') return setLimit('');
    const next = Math.min(Math.max(Number(raw), 1), count);
    setLimit(String(next));
  };

  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={t('confirm.title')}
      icon={AlertTriangle}
      footer={
        <>
          <Button variant="outline" onClick={onCancel}>
            {t('confirm.cancel')}
          </Button>
          <Button onClick={onConfirm}>{t('confirm.continue')}</Button>
        </>
      }
    >
      <p className="text-sm leading-relaxed text-muted-foreground">{t('confirm.body', { count })}</p>
      <div className="mt-5 space-y-1.5">
        <Label htmlFor="confirm-limit" className="text-xs text-muted-foreground">
          {t('confirm.limit')}
        </Label>
        <Input
          id="confirm-limit"
          type="number"
          inputMode="numeric"
          value={limit}
          min={1}
          max={count}
          onChange={(e) => handleLimitChange(e.target.value)}
          className="h-10 font-mono"
        />
      </div>
    </Modal>
  );
}
