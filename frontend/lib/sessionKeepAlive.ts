"use client";

/* Keep a session alive while someone is using it.

   A session token lives ACCESS_TOKEN_EXPIRE_MINUTES (60 by default) from sign-in. Without
   renewal, a person entering data was signed out an hour after signing in, mid-form,
   however busy they were. Now the token is swapped for a fresh one shortly before it
   runs out, but only if the person has done something recently: the token lifetime
   becomes the idle timeout, and the server caps the whole session (SESSION_MAX_HOURS). */

import { useEffect } from "react";
import { renewSession, tokenTimes } from "@/lib/api";

/** Renew once the token has less than this left… */
const RENEW_WHEN_LEFT_MS = 10 * 60 * 1000;
/** …and the person did something within this long. */
const ACTIVE_WITHIN_MS = 15 * 60 * 1000;
const CHECK_EVERY_MS = 30 * 1000;
const ACTIVITY = ["pointerdown", "keydown", "wheel", "touchstart"] as const;

export function useSessionKeepAlive(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    let lastActivity = Date.now();
    let renewing = false;
    const touch = () => { lastActivity = Date.now(); };
    ACTIVITY.forEach((e) => window.addEventListener(e, touch, { passive: true }));

    const check = async () => {
      const times = tokenTimes();
      if (!times || renewing) return;
      const left = times.exp * 1000 - Date.now();
      if (left <= 0 || left > RENEW_WHEN_LEFT_MS) return;
      if (Date.now() - lastActivity > ACTIVE_WITHIN_MS) return;
      renewing = true;
      try {
        await renewSession();
      } finally {
        renewing = false;
      }
    };
    const timer = window.setInterval(check, CHECK_EVERY_MS);
    // A tab brought back to the front checks at once: timers are throttled in the background.
    const onVisible = () => { if (document.visibilityState === "visible") void check(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      ACTIVITY.forEach((e) => window.removeEventListener(e, touch));
    };
  }, [enabled]);
}
