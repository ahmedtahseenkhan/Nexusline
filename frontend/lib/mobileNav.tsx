"use client";

import { useSyncExternalStore } from "react";

/** Shared open/close state for the off-canvas sidebar on small screens. The
 *  Topbar hamburger toggles it, the Sidebar reads it (and closes on navigation),
 *  and the layout renders a backdrop — all without threading props/context. */
let open = false;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

export function setMobileNav(next: boolean) {
  if (open === next) return;
  open = next;
  emit();
}

export function useMobileNav() {
  const isOpen = useSyncExternalStore(
    subscribe,
    () => open,
    () => false,
  );
  return {
    open: isOpen,
    setOpen: setMobileNav,
    toggle: () => setMobileNav(!open),
  };
}
