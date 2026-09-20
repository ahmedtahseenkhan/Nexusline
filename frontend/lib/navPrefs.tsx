"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { api, getToken, type Me } from "@/lib/api";

/** Per-user sidebar preferences: favorites (pinned modules), recently visited modules,
 *  and the groups the user has opened or closed themselves. Persisted in localStorage
 *  under the signed-in user's id, and shared across the Sidebar and Topbar via a tiny
 *  external store so a star toggle in one place updates the other immediately.
 *
 *  Keys: `nx.nav.<userId>.favorites | .recents | .groups`. The last user seen in this
 *  browser is remembered (`nx.nav.user`) so their preferences show on the first paint,
 *  before `/auth/me` answers. Favorites and recents kept under the older per-browser
 *  keys (`nx.nav.favorites`, `nx.nav.recents`) are copied to the first user who signs in
 *  after the upgrade, so nobody loses their pins. */
const LAST_USER_KEY = "nx.nav.user";
const LEGACY_FAV = "nx.nav.favorites";
const LEGACY_REC = "nx.nav.recents";
const REC_MAX = 6;

type Prefs = { favorites: string[]; recents: string[]; groups: Record<string, boolean> };
const EMPTY: Prefs = { favorites: [], recents: [], groups: {} };

let user: string | null = null;
let cache: Prefs | null = null;
const listeners = new Set<() => void>();

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function keys(u: string | null) {
  return u
    ? { fav: `nx.nav.${u}.favorites`, rec: `nx.nav.${u}.recents`, groups: `nx.nav.${u}.groups` }
    : { fav: LEGACY_FAV, rec: LEGACY_REC, groups: "nx.nav.groups" };
}

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = storage()?.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown) {
  try {
    storage()?.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode, quota — preferences simply are not remembered */
  }
}

function readRaw(): Prefs {
  if (typeof window === "undefined") return EMPTY;
  if (user === null) user = storage()?.getItem(LAST_USER_KEY) || null;
  const k = keys(user);
  return {
    favorites: readJson<string[]>(k.fav, []),
    recents: readJson<string[]>(k.rec, []),
    groups: readJson<Record<string, boolean>>(k.groups, {}),
  };
}

function getSnapshot(): Prefs {
  if (!cache) cache = readRaw();
  return cache;
}

function emit() {
  cache = readRaw();
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  const onStorage = (e: StorageEvent) => {
    if (e.key && e.key.startsWith("nx.nav.")) emit();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(l);
    window.removeEventListener("storage", onStorage);
  };
}

/** Switch the store to this user's preferences (called once `/auth/me` answers). */
export function setNavPrefsUser(id: string) {
  if (!id || id === user) return;
  user = id;
  const s = storage();
  s?.setItem(LAST_USER_KEY, id);
  const k = keys(id);
  // One-time upgrade: the per-browser favourites/recents become this user's.
  if (s && s.getItem(k.fav) === null && s.getItem(LEGACY_FAV) !== null) {
    s.setItem(k.fav, s.getItem(LEGACY_FAV) || "[]");
    s.setItem(k.rec, s.getItem(LEGACY_REC) || "[]");
    s.removeItem(LEGACY_FAV);
    s.removeItem(LEGACY_REC);
  }
  emit();
}

export function useNavPrefs() {
  const prefs = useSyncExternalStore(subscribe, getSnapshot, () => EMPTY);

  const toggleFavorite = useCallback((href: string) => {
    const cur = readRaw().favorites;
    const next = cur.includes(href) ? cur.filter((h) => h !== href) : [...cur, href];
    write(keys(user).fav, next);
    emit();
  }, []);

  const recordVisit = useCallback((href: string) => {
    const cur = readRaw().recents;
    if (cur[0] === href) return;
    write(keys(user).rec, [href, ...cur.filter((h) => h !== href)].slice(0, REC_MAX));
    emit();
  }, []);

  /** Remember that the user opened (true) or closed (false) a group. */
  const setGroupOpen = useCallback((title: string, open: boolean) => {
    write(keys(user).groups, { ...readRaw().groups, [title]: open });
    emit();
  }, []);

  /** Forget the user's own open/close choices: the role preset decides again. */
  const resetGroups = useCallback(() => {
    write(keys(user).groups, {});
    emit();
  }, []);

  return {
    favorites: prefs.favorites,
    recents: prefs.recents,
    groups: prefs.groups,
    isFavorite: (href: string) => prefs.favorites.includes(href),
    toggleFavorite,
    recordVisit,
    setGroupOpen,
    resetGroups,
  };
}

/* ---------------------------------------------------------- signed-in user --- */
/** What the navigation needs to know about the signed-in user. */
export type NavUser = { id: string; roles: string[]; permissions: string[]; platformAdmin: boolean };

let meRequest: { token: string | null; promise: Promise<NavUser | null> } | null = null;

function toNavUser(m: Me): NavUser {
  return {
    id: m.id,
    roles: (m.roles ?? []).map((r) => r.name),
    permissions: m.permission_codes ?? [],
    platformAdmin: !!m.is_platform_admin,
  };
}

/** `/auth/me` once per sign-in for the Sidebar and the command palette together (keyed
 *  by the session token, so a different user signing in in the same tab refetches). */
function loadNavUser(): Promise<NavUser | null> {
  const token = getToken();
  if (!meRequest || meRequest.token !== token) {
    meRequest = { token, promise: api.me().then(toNavUser).catch(() => null) };
  }
  return meRequest.promise;
}

/** The signed-in user for navigation (null until `/auth/me` answers, or on failure).
 *  Also switches the preference store to that user. */
export function useNavUser(): NavUser | null {
  const [me, setMe] = useState<NavUser | null>(null);
  useEffect(() => {
    let live = true;
    loadNavUser().then((u) => {
      if (!live) return;
      setMe(u);
      if (u) setNavPrefsUser(u.id);
    });
    return () => {
      live = false;
    };
  }, []);
  return me;
}
