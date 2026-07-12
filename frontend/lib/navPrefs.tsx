"use client";

import { useCallback, useSyncExternalStore } from "react";

/** Per-browser sidebar favorites (pinned modules) + recently-visited modules.
 *  Persisted in localStorage and shared across the Sidebar and Topbar via a tiny
 *  external store so a star toggle in one place updates the other immediately. */
const FAV_KEY = "nx.nav.favorites";
const REC_KEY = "nx.nav.recents";
const REC_MAX = 6;

type Prefs = { favorites: string[]; recents: string[] };
const EMPTY: Prefs = { favorites: [], recents: [] };

let cache: Prefs | null = null;
const listeners = new Set<() => void>();

function readRaw(): Prefs {
  if (typeof window === "undefined") return EMPTY;
  try {
    return {
      favorites: JSON.parse(localStorage.getItem(FAV_KEY) || "[]"),
      recents: JSON.parse(localStorage.getItem(REC_KEY) || "[]"),
    };
  } catch {
    return EMPTY;
  }
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
    if (e.key === FAV_KEY || e.key === REC_KEY) emit();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(l);
    window.removeEventListener("storage", onStorage);
  };
}

export function useNavPrefs() {
  const prefs = useSyncExternalStore(subscribe, getSnapshot, () => EMPTY);

  const toggleFavorite = useCallback((href: string) => {
    const cur = readRaw().favorites;
    const next = cur.includes(href) ? cur.filter((h) => h !== href) : [...cur, href];
    localStorage.setItem(FAV_KEY, JSON.stringify(next));
    emit();
  }, []);

  const recordVisit = useCallback((href: string) => {
    const cur = readRaw().recents.filter((h) => h !== href);
    localStorage.setItem(REC_KEY, JSON.stringify([href, ...cur].slice(0, REC_MAX)));
    emit();
  }, []);

  return {
    favorites: prefs.favorites,
    recents: prefs.recents,
    isFavorite: (href: string) => prefs.favorites.includes(href),
    toggleFavorite,
    recordVisit,
  };
}
