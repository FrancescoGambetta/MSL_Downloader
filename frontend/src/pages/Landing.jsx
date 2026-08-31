import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useAuth } from '@/lib/AuthContext';
import { useAppSettings } from '@/lib/AppSettingsContext';
import { getLastDisplayName } from '@/lib/sessionApi';
// Inlined as a raw string (Vite's `?raw` import) rather than loaded via
// `<img src>`: assets/Title.svg's accent detail is `fill:hsl(var(--primary))`,
// which only resolves against the live palette when the SVG is real DOM in
// this document -- an <img>-loaded SVG renders in its own isolated document,
// where that custom property doesn't exist, so palette switches (themes.js's
// applyPalette) would never reach it.
import logoSvg from '@/assets/Title.svg?raw';

// The app's entry point ("/"): logo, name, "Entra" -- landing here every time
// regardless of any remembered identity (see AuthContext.jsx) is the point,
// so it always asks before going anywhere. Login resumes/starts that name's
// session (webapi/session_routes.py -> data/sessions/<NAME>.json, the same
// history the legacy Streamlit app already kept), then always continues to
// the Catalog Manager.
export default function Landing() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const { t } = useAppSettings();
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    getLastDisplayName()
      .then(({ display_name }) => {
        if (display_name) setName(display_name);
      })
      .catch(() => {});
  }, []);

  const handleSubmit = async (event) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await login(trimmed);
      navigate('/catalog-manager');
    } catch (err) {
      setError(err.message || String(err));
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-12 px-4">
      {/* Wordmark's own fills are set in assets/Title.svg -- white body text,
          accent-colored icon detail that tracks the active palette -- so it
          reads directly on the page background, no backing plate needed. */}
      <div
        role="img"
        aria-label="MSL Image Downloader"
        className="h-28 w-auto sm:h-36 [&>svg]:h-full [&>svg]:w-auto"
        dangerouslySetInnerHTML={{ __html: logoSvg }}
      />

      <form onSubmit={handleSubmit} className="flex w-full max-w-sm flex-col items-center gap-4">
        <Input
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={t('landing.namePlaceholder')}
          autoFocus
          className="h-12 text-center text-base"
        />
        {error && <p className="text-xs text-destructive">{error}</p>}
        <Button type="submit" disabled={!name.trim() || submitting} className="h-12 w-full text-base">
          {submitting ? <Loader2 className="h-5 w-5 animate-spin" /> : <ArrowRight className="h-5 w-5" />}
          {t('landing.enter')}
        </Button>
      </form>
    </div>
  );
}
