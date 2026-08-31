// Shared by every Catalog Manager tab that tails a catalog_manager/jobs.py
// worker's raw stdout log (Updates, Personalize's customization runs, ...) --
// same log shape everywhere (`catalog_manager/workers/*.py`), so the same
// condense/classify rules apply regardless of which job kind is running.
import { AlertTriangle, CheckCircle2, Radio, SkipForward } from 'lucide-react';

const MAX_LOG_LINES = 80;

// The worker log is the raw stdout of a real scanning/filtering subprocess
// (one line per product it touches, full URL and all) -- readable for
// debugging, not for a user. Any "[..._product]"-tagged line is per-item
// noise by nature (there can be thousands); consecutive ones collapse into a
// single counted line, always, regardless of how many. Everything else --
// "[..._sol] sol=X | rmi_products=Y" and similar per-Sol summaries -- is
// already sparse and meaningful, so it passes through untouched. Generic by
// design -- works the same for every worker without knowing each one's exact
// log vocabulary, as long as per-item lines keep "product" in their tag.
// Tags that carry per-item noise (collapse into "× N") vs tags that, despite
// matching /product/i, carry real running progress and must stay visible
// line-by-line -- see CatalogUpdates.jsx's parseProgress(), which reads
// exactly this tag.
export const PROGRESS_TAGS = new Set(['camera_product_scan']);

export function condenseLog(raw) {
  const lines = raw.split('\n').filter((l) => l.trim());
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const match = lines[i].match(/^\[([a-z0-9_]+)\]/i);
    const tag = match ? match[1] : null;
    if (tag && /product/i.test(tag) && !PROGRESS_TAGS.has(tag)) {
      const group = [];
      while (i < lines.length && lines[i].match(/^\[([a-z0-9_]+)\]/i)?.[1] === tag) {
        group.push(lines[i]);
        i += 1;
      }
      out.push(`[${tag}] × ${group.length}`);
    } else {
      out.push(lines[i]);
      i += 1;
    }
  }
  return out.slice(-MAX_LOG_LINES);
}

// Classifies a (possibly condensed) raw log line into the same icon/color
// vocabulary as the download page's LiveLog, purely from its "[tag]" prefix
// and keywords -- this log has no structured {type} field like the download
// job's does, just plain worker stdout.
const LINE_META = {
  error: { icon: AlertTriangle, cls: 'text-destructive' },
  warning: { icon: AlertTriangle, cls: 'text-amber-500' },
  success: { icon: CheckCircle2, cls: 'text-emerald-500' },
  skip: { icon: SkipForward, cls: 'text-muted-foreground' },
  info: { icon: Radio, cls: 'text-muted-foreground' },
};

export function classifyLine(line) {
  const tag = line.match(/^\[([a-z0-9_]+)\]/i)?.[1]?.toLowerCase() || '';
  if (/error|exception|traceback|failed/i.test(line)) return LINE_META.error;
  if (/warning/i.test(line)) return LINE_META.warning;
  if (/(^|_)(done|checkpoint|catalog_live|installing)($|_)/.test(tag)) return LINE_META.success;
  if (/(^|_)(skip|missing)($|_)/.test(tag)) return LINE_META.skip;
  return LINE_META.info;
}

// Reads the latest "[X/Y] indexing SOL Z" scan progress and the latest
// running product count out of the raw worker log, for the small progress
// readout + bar shown while a job runs. Standard cameras (make_msl_catalog.py,
// used by both catalog updates and customization's own NASA-search phase)
// emit both directly ([camera_product_scan] for scan position, [catalog_live]
// for a running item total); ChemCam (make_msl_chemcam_catalog.py) emits
// neither -- it prints one [chemcam_sol]/[chemcam_sol_missing] line per Sol
// processed (no total in the line itself, so scanned-count comes from
// counting those lines against the job's requested Sol range) and its running
// product total only appears in periodic "[checkpoint] ... products=N" lines.
export function parseProgress(raw, job) {
  const lines = raw.split('\n');
  let scanned = null;
  let products = null;
  for (let i = lines.length - 1; i >= 0 && (scanned === null || products === null); i -= 1) {
    const line = lines[i];
    if (scanned === null) {
      const m = line.match(/\[camera_product_scan\][^[]*\[(\d+)\/(\d+)\]/);
      if (m) scanned = { done: Number(m[1]), total: Number(m[2]) };
    }
    if (products === null) {
      const m2 = line.match(/\[catalog_live\]\s*items=(\d+)/) || line.match(/\[checkpoint\][^|]*\|\s*products=(\d+)/);
      if (m2) products = Number(m2[1]);
    }
  }
  if (scanned === null && job?.sol_start != null && job?.sol_end != null) {
    const solLines = raw.match(/\[chemcam_sol(_missing)?\]/g);
    if (solLines) {
      const total = Math.max(1, Number(job.sol_end) - Number(job.sol_start) + 1);
      scanned = { done: Math.min(solLines.length, total), total };
    }
  }
  return { scanned, products };
}
