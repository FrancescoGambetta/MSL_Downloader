// Minimal localStorage-backed entity store, replacing the old remote
// entities API now that there is no backend to persist to. Every "saved" record
// (downloaded image metadata, etc.) lives in the browser's localStorage.
// The surface intentionally mirrors what the rest of the app already
// expects: entity.list(sort, limit) and entity.create(record).

function makeEntityStore(storageKey) {
  function readAll() {
    try {
      const raw = localStorage.getItem(storageKey);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  }

  function writeAll(items) {
    try {
      localStorage.setItem(storageKey, JSON.stringify(items));
    } catch {
      /* storage full or unavailable — best effort only */
    }
  }

  return {
    async list(sort, limit) {
      let items = readAll();
      if (sort) {
        const desc = sort.startsWith('-');
        const key = desc ? sort.slice(1) : sort;
        items = [...items].sort((a, b) => {
          const av = a[key];
          const bv = b[key];
          if (av === bv) return 0;
          return (av > bv ? 1 : -1) * (desc ? -1 : 1);
        });
      }
      return typeof limit === 'number' ? items.slice(0, limit) : items;
    },

    async create(record) {
      const items = readAll();
      const created = {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
        created_date: new Date().toISOString(),
        ...record,
      };
      items.push(created);
      writeAll(items);
      return created;
    },

    async remove(id) {
      writeAll(readAll().filter((item) => item.id !== id));
    },

    async clear() {
      writeAll([]);
    },
  };
}

export const localEntities = {
  DownloadedImage: makeEntityStore('msl_entity_downloaded_image'),
};
