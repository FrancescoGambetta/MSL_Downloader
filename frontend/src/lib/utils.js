import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

// Merges conditional class names and resolves conflicting Tailwind utilities,
// so a caller's `className` always wins over a component's defaults.
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}
