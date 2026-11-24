/**
 * Own encrypted IndexedDB records, account scope, non-exportable keys, expiry and cross-tab fencing.
 * Maintainer map: docs/FRONTEND_GUIDE.md and docs/reference/FRONTEND.md.
 */
/* Encrypted browser storage. Persist non-exportable keys, never raw key bytes. */
(() => {
  "use strict";
  const DB = "nurse-offline-v1",
    ACTIVE = "nurse-offline-active",
    CONTEXT = "nurse-offline-context";
  const SIGNAL = "nurse-offline-signal",
    REVOKED = "nurse-offline-revoked";
  const IDENTITY = "@identity",
    FOREVER = Number.MAX_SAFE_INTEGER;
  const enc = new TextEncoder(),
    dec = new TextDecoder(),
    LEASE = 15000;
  let db,
    context,
    key,
    available = false,
    error = "",
    channel;
  const changed = () =>
    document.dispatchEvent(new Event("nurse:offline-change"));
  const sessionError = () =>
    new Error("Reconnect and sign in before using your offline data.");
  const lockError = () =>
    new Error(
      "Another tab took over this change. Reopen the saved item before trying again.",
    );
  const same = (a, b) => a?.scope === b?.scope && a?.epoch === b?.epoch;
  const vaultId = (scope) => "@vault:" + scope;
  const revocationId = (owner) =>
    REVOKED + ":" + owner.scope + ":" + owner.epoch;
  function revoked(owner) {
    try {
      return !!owner && localStorage.getItem(revocationId(owner)) === "1";
    } catch {
      return false;
    }
  }
  function transaction(mode, action) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction("records", mode);
      let value, failure;
      const fail = (reason) => {
        failure = reason;
        tx.abort();
      };
      try {
        action(
          tx.objectStore("records"),
          (result) => {
            value = result;
          },
          fail,
        );
      } catch (reason) {
        fail(reason);
      }
      tx.oncomplete = () => resolve(value);
      tx.onabort = tx.onerror = () =>
        reject(failure || tx.error || new Error("Local storage failed."));
    });
  }
  function result(req, done) {
    req.onsuccess = () => done(req.result);
  }
  const read = (id) =>
    transaction("readonly", (rows, done) => result(rows.get(id), done));
  function purge(rows, scope, done) {
    rows.index("scope").openKeyCursor(IDBKeyRange.only(scope)).onsuccess = (
      event,
    ) => {
      const cursor = event.target.result;
      if (!cursor) {
        done();
        return;
      }
      rows.delete(cursor.primaryKey);
      cursor.continue();
    };
  }
  function lockMemory(owner = context) {
    if (owner && context && !same(owner, context)) return;
    available = false;
    key = null;
    context = null;
    changed();
  }
  function locked(owner = context) {
    if (revoked(owner)) {
      lockMemory(owner);
      throw sessionError();
    }
    if (!available || !owner || context !== owner) throw sessionError();
  }
  // The identity and lease checks share the transaction with every data mutation.
  // A suspended tab cannot write after sign-out, workspace replacement or lease takeover.
  async function guarded(mode, owner, fence, action) {
    locked(owner);
    return transaction(mode, (rows, done, fail) => {
      rows.get(IDENTITY).onsuccess = (event) => {
        if (!same(event.target.result, owner)) {
          lockMemory(owner);
          fail(sessionError());
          return;
        }
        const run = () => {
          try {
            locked(owner);
            action(rows, done, fail);
          } catch (reason) {
            fail(reason);
          }
        };
        if (!fence) {
          run();
          return;
        }
        rows.get(fence.id).onsuccess = (event) => {
          const lease = event.target.result;
          if (
            !fence.active ||
            lease?.token !== fence.token ||
            lease.expires <= Date.now()
          ) {
            fence.active = false;
            fail(lockError());
            return;
          }
          run();
        };
      };
    });
  }
  function announce(type = "change", detail = {}) {
    const message = {
      type,
      scope: context?.scope,
      epoch: context?.epoch,
      ...detail,
      nonce: crypto.randomUUID(),
    };
    try {
      channel?.postMessage(message);
    } catch {
      /* Storage events are the fallback. */
    }
    try {
      localStorage.setItem(SIGNAL, JSON.stringify(message));
    } catch {
      /* IndexedDB remains authoritative. */
    }
    if (type !== "confirmed") changed();
  }
  async function receive(message) {
    if (!available) return;
    const owner = context;
    if (revoked(owner) || !same(await read(IDENTITY), owner)) {
      lockMemory(owner);
      return;
    }
    if (context !== owner || !message || !same(message, owner)) return;
    if (message.type === "confirmed") {
      const op = await get("operation", message.id);
      if (op?.status === "confirmed")
        document.dispatchEvent(
          new CustomEvent("nurse:operation-confirmed", { detail: op }),
        );
    } else changed();
  }
  async function open() {
    db = await new Promise((resolve, reject) => {
      // Keep v3 so open tabs from the previous release cannot block installation.
      const req = indexedDB.open(DB, 3);
      req.onupgradeneeded = () => {
        const rows = req.result.objectStoreNames.contains("records")
          ? req.transaction.objectStore("records")
          : req.result.createObjectStore("records", { keyPath: "id" });
        if (!rows.indexNames.contains("owner-kind"))
          rows.createIndex("owner-kind", ["scope", "tab", "kind"]);
        if (!rows.indexNames.contains("scope"))
          rows.createIndex("scope", "scope");
        if (!rows.indexNames.contains("expires"))
          rows.createIndex("expires", "expires");
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    db.onversionchange = () => {
      db.close();
      lockMemory();
    };
    await transaction("readwrite", (rows) => {
      rows
        .index("expires")
        .openKeyCursor(IDBKeyRange.upperBound(Date.now())).onsuccess = (
        event,
      ) => {
        const cursor = event.target.result;
        if (cursor) {
          rows.delete(cursor.primaryKey);
          cursor.continue();
        }
      };
    });
    if (!channel && "BroadcastChannel" in window) {
      channel = new BroadcastChannel("nurse-offline");
      channel.onmessage = (event) => receive(event.data).catch(() => {});
    }
  }
  async function withLock(name, action, { ifAvailable = false } = {}) {
    locked();
    const owner = context;
    const id = "@lock:" + owner.scope + ":" + owner.epoch + ":" + name;
    const run = async () => {
      const fence = { id, token: crypto.randomUUID(), active: true };
      const row = () => ({
        id,
        scope: owner.scope,
        tab: owner.tab,
        kind: "_lock",
        token: fence.token,
        expires: Date.now() + LEASE,
      });
      const start = Date.now();
      while (
        !(await guarded("readwrite", owner, null, (rows, done) => {
          rows.get(id).onsuccess = (event) => {
            if (event.target.result?.expires > Date.now()) {
              done(false);
              return;
            }
            rows.put(row());
            done(true);
          };
        }))
      ) {
        if (ifAvailable) return;
        if (Date.now() - start > 45000)
          throw new Error("Another tab is saving. Try again shortly.");
        await new Promise((resolve) =>
          setTimeout(resolve, 80 + Math.random() * 120),
        );
      }
      fence.check = () =>
        guarded("readonly", owner, fence, (_rows, done) => done(true));
      const timer = setInterval(() => {
        guarded("readwrite", owner, fence, (rows) => rows.put(row())).catch(
          () => {
            fence.active = false;
          },
        );
      }, LEASE / 3);
      try {
        return await action(fence);
      } finally {
        clearInterval(timer);
        fence.active = false;
        await transaction("readwrite", (rows) => {
          rows.get(id).onsuccess = (event) => {
            if (event.target.result?.token === fence.token) rows.delete(id);
          };
        }).catch(() => {});
      }
    };
    // Leases also coordinate tabs where Web Locks is unavailable. Late writes are fenced.
    if (navigator.locks?.request)
      return navigator.locks.request(id, { ifAvailable }, (lock) =>
        lock ? run() : undefined,
      );
    return run();
  }
  const prefix = (owner) => owner.scope + ":" + owner.tab + ":";
  async function encode(owner, secret, kind, id, value, options = {}) {
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const bytes = options.binary ? value : enc.encode(JSON.stringify(value));
    const cipher = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      secret,
      bytes,
    );
    return {
      id: prefix(owner) + kind + ":" + id,
      scope: owner.scope,
      tab: owner.tab,
      kind,
      item: id,
      iv,
      cipher,
      binary: !!options.binary,
      saved: Date.now(),
      expires: Date.now() + (options.ttl || 86400000),
    };
  }
  async function putMany(entries, fence) {
    locked();
    const owner = context,
      secret = key,
      rows = [];
    for (const { kind, id, value, options } of entries)
      rows.push(await encode(owner, secret, kind, id, value, options));
    await guarded("readwrite", owner, fence, (store) => {
      for (const row of rows) store.put(row);
    });
    announce();
  }
  const put = (kind, id, value, options, fence) =>
    putMany([{ kind, id, value, options }], fence);
  async function decode(row, owner, secret) {
    if (!row || row.expires <= Date.now()) return null;
    if (row.scope !== owner.scope || row.tab !== owner.tab) return null;
    const bytes = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: row.iv },
      secret,
      row.cipher,
    );
    return row.binary ? bytes : JSON.parse(dec.decode(bytes));
  }
  async function get(kind, id) {
    locked();
    const owner = context,
      secret = key;
    const row = await guarded("readonly", owner, null, (rows, done) =>
      result(rows.get(prefix(owner) + kind + ":" + id), done),
    );
    const value = await decode(row, owner, secret);
    await guarded("readonly", owner, null, (_rows, done) => done(true));
    return value;
  }
  async function list(kind) {
    locked();
    const owner = context,
      secret = key;
    const rows = await guarded("readonly", owner, null, (rows, done) =>
      result(
        rows.index("owner-kind").getAll([owner.scope, owner.tab, kind]),
        done,
      ),
    );
    const values = [];
    for (const row of rows) {
      const value = await decode(row, owner, secret);
      if (value !== null)
        values.push({ id: row.item, saved: row.saved, value });
    }
    await guarded("readonly", owner, null, (_rows, done) => done(true));
    return values;
  }
  async function remove(kind, id, fence) {
    const owner = context;
    await guarded("readwrite", owner, fence, (rows) =>
      rows.delete(prefix(owner) + kind + ":" + id),
    );
    announce();
  }
  async function clear(owner = context) {
    // Revocation survives closing a page before its deletion transaction finishes.
    // A tab that is already locked must never clear a newer account's workspace.
    if (owner) {
      try {
        localStorage.setItem(revocationId(owner), "1");
      } catch {
        /* IndexedDB deletion still applies. */
      }
    }
    lockMemory(owner);
    try {
      sessionStorage.removeItem(CONTEXT);
    } catch {
      /* May already be unavailable. */
    }
    if (!db || !owner) return;
    const cleared = await transaction("readwrite", (rows, done) => {
      rows.get(IDENTITY).onsuccess = (event) => {
        if (!same(event.target.result, owner)) {
          done(false);
          return;
        }
        purge(rows, owner.scope, () => done(true));
      };
    });
    if (cleared) {
      try {
        if (localStorage.getItem(ACTIVE) === owner.scope)
          localStorage.setItem(ACTIVE, "");
      } catch {
        /* Best effort. */
      }
      announce("cleared", owner);
    }
  }
  // A secondary legacy tab gets its own recovered draft IDs. Never replace newer
  // drafts or change the server operation UUID/payload while importing old data.
  async function migrate(fence) {
    const owner = context,
      secret = key;
    const all = await guarded("readonly", owner, fence, (rows, done) =>
      result(rows.index("scope").getAll(owner.scope), done),
    );
    for (const legacy of all.filter((row) => row.kind === "_legacy")) {
      const source = all.filter(
        (row) => row.tab === legacy.tab && !row.kind.startsWith("_"),
      );
      const recovered = (id) => id + ":recovered:" + legacy.tab;
      const migrated = [];
      for (const row of source) {
        let value = await decode(row, legacy, legacy.key),
          id = row.item;
        if (value === null) continue;
        if (row.kind === "draft") {
          id = recovered(id);
          value = { ...value, id, title: value.title + " (recovered)" };
        }
        if (row.kind === "operation" && value.metadata?.draft) {
          const ref = value.metadata.draft;
          value = {
            ...value,
            target: value.target === ref.id ? recovered(ref.id) : value.target,
            metadata: {
              ...value.metadata,
              draft: { ...ref, id: recovered(ref.id) },
            },
          };
        }
        const copy = await encode(owner, secret, row.kind, id, value, {
          binary: row.binary,
        });
        copy.saved = row.saved;
        copy.expires = row.expires;
        migrated.push(copy);
      }
      await guarded("readwrite", owner, fence, (rows, _done, fail) => {
        rows.index("scope").getAll(owner.scope).onsuccess = (event) => {
          const latest = event.target.result.filter(
            (row) => row.tab === legacy.tab && !row.kind.startsWith("_"),
          );
          const signature = (rows) =>
            JSON.stringify(
              rows.map((row) => [row.id, row.saved, Array.from(row.iv)]),
            );
          if (signature(latest) !== signature(source)) {
            fail(
              new Error(
                "An older tab is still saving. Reload it to finish recovery.",
              ),
            );
            return;
          }
          for (const copy of migrated)
            rows.get(copy.id).onsuccess = (event) => {
              try {
                if (
                  !event.target.result ||
                  event.target.result.saved < copy.saved
                )
                  rows.put(copy);
              } catch (reason) {
                fail(reason);
              }
            };
          for (const row of source) rows.delete(row.id);
          rows.delete(legacy.id);
        };
      });
    }
  }
  async function init(scope, known) {
    if (!window.isSecureContext || !window.indexedDB || !crypto.subtle)
      return false;
    try {
      await open();
      let before = await read(IDENTITY);
      let legacy;
      try {
        legacy = JSON.parse(sessionStorage.getItem(CONTEXT) || "null");
      } catch {
        /* Fresh or restricted tab. */
      }
      let previous;
      try {
        previous = localStorage.getItem(ACTIVE);
      } catch {
        /* IndexedDB can work independently. */
      }
      if (revoked(before)) {
        await clear(before);
        before = null;
        legacy = null;
        previous = "";
        if (!known) return false;
      }
      if (known && !scope) {
        await clear(before);
        // A pre-upgrade sign-out may have no durable identity yet.
        if (!before && previous) {
          await transaction("readwrite", (rows) =>
            purge(rows, previous, () => {}),
          );
          try {
            if (localStorage.getItem(ACTIVE) === previous)
              localStorage.setItem(ACTIVE, "");
          } catch {
            /* Best effort. */
          }
        }
        return false;
      }
      if (!known)
        scope =
          before?.scope || (previous === legacy?.scope ? legacy.scope : "");
      if (!scope) return false;
      if (
        legacy?.scope !== scope ||
        !Array.isArray(legacy.secret) ||
        legacy.secret.length !== 32
      )
        legacy = null;
      const candidate = legacy
        ? await crypto.subtle.importKey(
            "raw",
            new Uint8Array(legacy.secret),
            "AES-GCM",
            false,
            ["encrypt", "decrypt"],
          )
        : await crypto.subtle.generateKey(
            { name: "AES-GCM", length: 256 },
            false,
            ["encrypt", "decrypt"],
          );
      const vault = await transaction("readwrite", (rows, done, fail) => {
        rows.get(IDENTITY).onsuccess = (event) => {
          const current = event.target.result;
          if (current?.scope !== scope && !same(current, before)) {
            fail(sessionError());
            return;
          }
          if (!known && current && current.scope !== scope) {
            fail(sessionError());
            return;
          }
          rows.get(vaultId(scope)).onsuccess = (event) => {
            const saved = event.target.result || {
              id: vaultId(scope),
              kind: "_vault",
              scope,
              tab: legacy?.tab || crypto.randomUUID(),
              epoch: crypto.randomUUID(),
              key: candidate,
              expires: FOREVER,
            };
            const activate = () => {
              try {
                rows.put(saved);
                rows.put({
                  id: IDENTITY,
                  kind: "_identity",
                  scope,
                  epoch: saved.epoch,
                  expires: FOREVER,
                });
                if (legacy && legacy.tab !== saved.tab)
                  rows.put({
                    id: "@legacy:" + scope + ":" + legacy.tab,
                    kind: "_legacy",
                    scope,
                    tab: legacy.tab,
                    key: candidate,
                    expires: FOREVER,
                  });
                done(saved);
              } catch (reason) {
                fail(reason);
              }
            };
            if (current && current.scope !== scope)
              purge(rows, current.scope, activate);
            else if (!current && previous && previous !== scope)
              purge(rows, previous, activate);
            else activate();
          };
        };
      });
      context = { scope, tab: vault.tab, epoch: vault.epoch };
      key = vault.key;
      available = true;
      // Only remove the raw legacy secret after its non-exportable key is committed.
      try {
        sessionStorage.removeItem(CONTEXT);
      } catch {
        /* The durable key is already saved. */
      }
      try {
        localStorage.setItem(ACTIVE, scope);
      } catch {
        /* IndexedDB owns the identity. */
      }
      try {
        await withLock("changes", migrate);
      } catch {
        error =
          "Some older drafts could not be recovered yet. Their keys and data are preserved. Free browser storage and reopen the app to retry.";
      }
      navigator.storage?.persist?.().catch(() => {});
      announce();
      return true;
    } catch {
      lockMemory();
      error =
        "Offline storage could not be prepared. Existing tab data has been kept. Allow browser storage or free some space, then reload.";
      return false;
    }
  }
  async function saveFile(file, fence) {
    locked();
    if (file.size > 100 * 1024 * 1024)
      throw new Error("This file exceeds the 100 MB offline limit.");
    const estimate = await navigator.storage?.estimate?.();
    if (estimate?.quota && estimate.quota - estimate.usage < file.size * 1.2)
      throw new Error("Not enough device storage.");
    const id = crypto.randomUUID(),
      size = 1024 * 1024;
    try {
      for (let offset = 0; offset < file.size; offset += size) {
        await put(
          "file-chunk",
          id + ":" + offset,
          await file.slice(offset, offset + size).arrayBuffer(),
          { binary: true, ttl: 7 * 86400000 },
          fence,
        );
      }
      await put(
        "file",
        id,
        { name: file.name, type: file.type, size: file.size, chunk: size },
        { ttl: 7 * 86400000 },
        fence,
      );
      return id;
    } catch (reason) {
      await removeFile(id).catch(() => {});
      throw reason;
    }
  }
  async function removeFile(id, fence) {
    const owner = context,
      start = prefix(owner) + "file-chunk:" + id + ":";
    await guarded("readwrite", owner, fence, (rows) => {
      rows.delete(prefix(owner) + "file:" + id);
      rows.delete(IDBKeyRange.bound(start, start + "\uffff"));
    });
    announce();
  }
  window.addEventListener("storage", (event) => {
    if (
      event.key === SIGNAL ||
      event.key === ACTIVE ||
      event.key?.startsWith(REVOKED + ":") ||
      event.key === null
    ) {
      let message;
      try {
        message = JSON.parse(event.key === SIGNAL ? event.newValue : "null");
      } catch {
        /* Ignore invalid hints. */
      }
      receive(message).catch(() => {});
    }
  });
  window.addEventListener("pageshow", () => {
    if (db) receive().catch(() => {});
  });
  document.addEventListener("nurse:signed-out", () => clear().catch(() => {}));
  window.NurseOfflineStore = {
    init,
    get,
    put,
    putMany,
    list,
    remove,
    clear,
    saveFile,
    removeFile,
    withLock,
    announce,
    get available() {
      return available;
    },
    get scope() {
      return context?.scope || "";
    },
    get error() {
      return error;
    },
  };
})();
