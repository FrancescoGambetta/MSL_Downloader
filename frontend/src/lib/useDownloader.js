import { useCallback, useEffect, useRef, useState } from 'react';
import { localEntities } from '@/lib/localDb';
import { searchPhotos, startDownloadJob, fetchDownloadJob, cancelDownloadJob, fileUrl } from '@/lib/mslApi';
import { useAppSettings } from '@/lib/AppSettingsContext';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const POLL_INTERVAL_MS = 500;
// A poll can return several new log lines at once (the backend appends them
// faster than the UI polls). Revealing them with a small stagger instead of
// dumping the whole batch into state in one React update is what makes the
// log read as a smooth trickle instead of a big block of text landing at once.
// This stagger runs on its own queue+timer (see logQueueRef below), never
// inside the poll loop itself -- progress/status must stay real-time even
// while a big burst of log lines is still trickling in on screen.
const LOG_REVEAL_STAGGER_MS = 45;

const MAX_LOG_ENTRIES = 200;

export function useDownloader() {
  const { t, settings } = useAppSettings();
  const [isSearching, setIsSearching] = useState(false);
  const [foundRecords, setFoundRecords] = useState([]);
  const [appliedFilters, setAppliedFilters] = useState(null);
  const [log, setLog] = useState([]);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [isRunning, setIsRunning] = useState(false);
  const [savedImages, setSavedImages] = useState([]);
  const [selectedImage, setSelectedImage] = useState(null);
  const [lastError, setLastError] = useState(null);
  const stopFlag = useRef(false);

  // Product ids already on disk, kept in a ref so `runDownload` doesn't need
  // `savedImages` as a dependency — otherwise every saved record rebuilt the
  // callback mid-run and the loop kept a stale copy of the set.
  const savedIdsRef = useRef(new Set());

  const addLog = useCallback((type, message) => {
    setLog((prev) => [
      ...prev.slice(-(MAX_LOG_ENTRIES - 1)),
      { id: `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`, type, message, ts: new Date() },
    ]);
  }, []);

  // Log entries arrive from the poll loop in bursts (the backend produces
  // them faster than the 500ms poll cadence); this queue+timer reveals them
  // one at a time at a readable pace, completely decoupled from polling
  // itself -- progress/status updates must never wait on how many log lines
  // are still queued up to be shown.
  const logQueueRef = useRef([]);
  const revealTimerRef = useRef(null);

  const drainLogQueue = useCallback(() => {
    if (logQueueRef.current.length === 0) {
      revealTimerRef.current = null;
      return;
    }
    const entry = logQueueRef.current.shift();
    addLog(entry.type, entry.message);
    revealTimerRef.current = setTimeout(drainLogQueue, LOG_REVEAL_STAGGER_MS);
  }, [addLog]);

  const enqueueLog = useCallback(
    (entries) => {
      if (!entries.length) return;
      logQueueRef.current.push(...entries);
      if (revealTimerRef.current === null) {
        drainLogQueue();
      }
    },
    [drainLogQueue]
  );

  useEffect(
    () => () => {
      if (revealTimerRef.current) clearTimeout(revealTimerRef.current);
    },
    []
  );

  const loadSaved = useCallback(async () => {
    try {
      const list = (await localEntities.DownloadedImage.list('-created_date', 200)) || [];
      // Recompute img_src fresh on every load rather than trusting the
      // persisted string: a job_id living only in the webapi's in-memory
      // registry doesn't survive a server restart, but the root hint lets the
      // backend still find the file by name. Records saved before this field
      // existed just keep whatever img_src they already had.
      const withFreshUrls = list.map((item) =>
        item.job_id ? { ...item, img_src: fileUrl(item.job_id, item.product_id, item.output_root) } : item
      );
      setSavedImages(withFreshUrls);
      savedIdsRef.current = new Set(list.map((item) => item.product_id));
    } catch {
      /* localStorage unavailable — the gallery just stays empty */
    }
  }, []);

  useEffect(() => {
    loadSaved();
  }, [loadSaved]);

  const clearSaved = useCallback(async () => {
    try {
      await localEntities.DownloadedImage.clear();
      setSavedImages([]);
      savedIdsRef.current = new Set();
      setSelectedImage(null);
    } catch {
      /* localStorage unavailable */
    }
  }, []);

  const applyFilters = useCallback(
    async (filters) => {
      setIsSearching(true);
      setLastError(null);
      setFoundRecords([]);
      setAppliedFilters(null);
      addLog(
        'info',
        t('log.search', {
          start: filters.solStart,
          end: filters.solEnd,
          cameras: filters.cameras.join(', ') || t('log.noCameras'),
        })
      );
      try {
        const { photos, totalFound, error } = await searchPhotos({
          solStart: filters.solStart,
          solEnd: filters.solEnd,
          cameras: filters.cameras,
          catalog: filters.catalog,
          minSize: filters.minSize,
          outputFolder: filters.outputFolder,
          organization: filters.organization,
        });

        if (error === '429') {
          setLastError('rate_limit');
          addLog('error', t('log.rateLimited'));
        } else if (error === 'network') {
          setLastError('network');
          addLog('error', t('log.apiUnreachable'));
        }

        // Server-side filtering already applied Sol range, camere, catalogo e
        // dimensione minima (stesso motore camera_rules.json della sidebar
        // reale) — qui resta solo il tetto massimo immagini, lato client.
        const capped = filters.maxImages > 0 ? photos.slice(0, filters.maxImages) : photos;

        setFoundRecords(capped);
        setAppliedFilters({ ...filters, totalFound, afterFilters: capped.length });
        addLog('success', t('log.found', { count: capped.length, total: totalFound }));
      } catch (error) {
        setLastError('unknown');
        addLog('error', t('log.searchError', { error: error.message || error }));
      } finally {
        setIsSearching(false);
      }
    },
    [addLog, t]
  );

  const activeJobId = useRef(null);

  const runDownload = useCallback(
    async (records) => {
      if (!records.length || isRunning) return;

      const toDownload = [];
      let alreadyPresent = 0;
      for (const rec of records) {
        if (savedIdsRef.current.has(rec.product_id)) {
          alreadyPresent += 1;
        } else {
          toDownload.push(rec);
        }
      }
      if (alreadyPresent) {
        addLog('skip', t('log.alreadyPresent', { count: alreadyPresent }));
      }
      if (!toDownload.length) {
        addLog('info', t('log.nothingToDownload'));
        return;
      }

      stopFlag.current = false;
      setIsRunning(true);
      setProgress({ done: 0, total: toDownload.length });
      addLog('info', t('log.startingDownload', { count: toDownload.length }));

      let jobId;
      let outputRoot;
      try {
        const started = await startDownloadJob(
          toDownload,
          appliedFilters?.outputFolder,
          appliedFilters?.organization,
          settings.language
        );
        jobId = started.jobId;
        outputRoot = started.outputFolder;
        activeJobId.current = jobId;
        addLog('info', t('log.destinationFolder', { folder: started.outputFolder }));
      } catch (error) {
        addLog('error', t('log.startFailed', { error: error.message || error }));
        setIsRunning(false);
        return;
      }

      // Tracks the highest log entry `seq` already queued for display, not
      // how many entries have been consumed -- the backend's job.log is a
      // bounded ring buffer (old entries age out once a job produces enough
      // of them), so a plain "how many have I seen" count eventually exceeds
      // the trimmed array's length and would make every future poll compute
      // zero new entries forever, even though the job is still very much
      // producing them. `seq` is assigned once per entry and never reused,
      // so filtering by it stays correct no matter how much trimming happens.
      let lastSeq = 0;
      let finished = false;
      while (!finished) {
        if (stopFlag.current) {
          await cancelDownloadJob(jobId);
        }
        await sleep(POLL_INTERVAL_MS);
        let job;
        try {
          job = await fetchDownloadJob(jobId);
        } catch (error) {
          addLog('error', t('log.statusReadFailed', { error: error.message || error }));
          break;
        }

        const newEntries = (job.log || []).filter((entry) => (entry.seq ?? 0) > lastSeq);
        if (newEntries.length) {
          lastSeq = Math.max(lastSeq, ...newEntries.map((entry) => entry.seq ?? 0));
          enqueueLog(newEntries);
        }
        setProgress(job.progress || { done: 0, total: toDownload.length });

        if (job.status !== 'running') {
          finished = true;
          const succeededIds = new Set(job.result?.succeeded_product_ids || []);
          const outputFiles = job.result?.output_files || {};
          // Register only the records the job actually reported as succeeded,
          // pointing img_src at the real processed JPG the job just wrote
          // (served by webapi, not the original remote NASA URL).
          for (const rec of toDownload) {
            if (!succeededIds.has(rec.product_id)) continue;
            const hasRealFile = Object.prototype.hasOwnProperty.call(outputFiles, rec.product_id);
            try {
              await localEntities.DownloadedImage.create({
                ...rec,
                status: 'downloaded',
                // job_id/output_root (not just a pre-baked img_src) are kept so
                // loadSaved() can always recompute a working preview URL later,
                // even after a webapi restart wipes this job from memory (see
                // fileUrl's root-hint fallback in webapi/download_service.py).
                job_id: hasRealFile ? jobId : rec.job_id,
                output_root: hasRealFile ? outputRoot : rec.output_root,
                img_src: hasRealFile ? fileUrl(jobId, rec.product_id, outputRoot) : rec.img_src,
              });
              savedIdsRef.current.add(rec.product_id);
            } catch {
              /* localStorage unavailable */
            }
          }
        }
      }

      activeJobId.current = null;
      setIsRunning(false);
      await loadSaved();
    },
    [addLog, appliedFilters, enqueueLog, isRunning, loadSaved, settings.language, t]
  );

  const stop = useCallback(() => {
    stopFlag.current = true;
    if (activeJobId.current) {
      cancelDownloadJob(activeJobId.current);
    }
  }, []);

  const clearLog = useCallback(() => {
    logQueueRef.current = [];
    if (revealTimerRef.current) {
      clearTimeout(revealTimerRef.current);
      revealTimerRef.current = null;
    }
    setLog([]);
  }, []);

  return {
    isSearching,
    foundRecords,
    appliedFilters,
    log,
    progress,
    isRunning,
    savedImages,
    selectedImage,
    setSelectedImage,
    lastError,
    applyFilters,
    runDownload,
    stop,
    clearLog,
    loadSaved,
    clearSaved,
  };
}
