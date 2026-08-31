import { useEffect, useState } from 'react';

// Layout state that CSS alone can't express — e.g. "the drawer is a drawer
// right now, so lock the page behind it".
export function useMediaQuery(query) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);

  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = (e) => setMatches(e.matches);
    setMatches(mql.matches);
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, [query]);

  return matches;
}

// Mirrors the `lg` Tailwind breakpoint, where the sidebar stops being a drawer.
export const DESKTOP_QUERY = '(min-width: 1024px)';
