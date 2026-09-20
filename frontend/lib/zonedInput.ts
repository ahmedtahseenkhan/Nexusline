/* `<input type="datetime-local">` in the organisation's timezone.

   A datetime-local input holds a wall-clock time with no zone ("2026-09-01T14:30"). The
   organisation's timezone (Settings → Organisation) decides what that wall clock means,
   not the browser's: a SOC analyst in Dubai logging a Karachi bank's incident types
   Karachi time. These two helpers convert between the input's value and an ISO 8601
   timestamp with the organisation's offset, which is what the API stores.

     toZonedInput("2026-09-01T09:30:00Z", "Asia/Karachi")   // "2026-09-01T14:30"
     fromZonedInput("2026-09-01T14:30", "Asia/Karachi")     // "2026-09-01T14:30:00+05:00"
*/

const partFormatters = new Map<string, Intl.DateTimeFormat>();

function formatter(timeZone: string): Intl.DateTimeFormat {
  let f = partFormatters.get(timeZone);
  if (!f) {
    const opts: Intl.DateTimeFormatOptions = {
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
    };
    try {
      f = new Intl.DateTimeFormat("en-GB", { ...opts, timeZone });
    } catch {
      f = new Intl.DateTimeFormat("en-GB", opts); // unknown zone: the browser's own
    }
    partFormatters.set(timeZone, f);
  }
  return f;
}

function wallParts(instant: number, timeZone: string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const p of formatter(timeZone).formatToParts(new Date(instant))) {
    if (p.type !== "literal") out[p.type] = Number(p.value);
  }
  return out;
}

/** Minutes the zone is ahead of UTC at `instant` (Asia/Karachi: 300). */
export function zoneOffsetMinutes(timeZone: string, instant: number): number {
  const p = wallParts(instant, timeZone);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
  return Math.round((asUtc - Math.floor(instant / 1000) * 1000) / 60000);
}

const pad = (n: number) => String(Math.abs(n)).padStart(2, "0");

/** The datetime-local value ("YYYY-MM-DDTHH:mm") for a stored timestamp, in `timeZone`.
 *  A bare date ("2026-09-01") is that day at 00:00; blank/unparseable gives "". */
export function toZonedInput(value: string | null | undefined, timeZone: string): string {
  if (!value) return "";
  const text = value.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return `${text}T00:00`;
  const t = new Date(text).getTime();
  if (Number.isNaN(t)) return "";
  const p = wallParts(t, timeZone);
  return `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}`;
}

/** An ISO 8601 timestamp with `timeZone`'s offset for a datetime-local value; null when
 *  blank. Around a daylight-saving change the offset in force at that wall time wins. */
export function fromZonedInput(local: string | null | undefined, timeZone: string): string | null {
  if (!local) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(local.trim());
  if (!m) return null;
  const [y, mo, d, h, mi] = [m[1], m[2], m[3], m[4] ?? "00", m[5] ?? "00"].map(Number);
  const guess = Date.UTC(y, mo - 1, d, h, mi);
  let offset = zoneOffsetMinutes(timeZone, guess);
  const second = zoneOffsetMinutes(timeZone, guess - offset * 60000);
  if (second !== offset) offset = second;
  const sign = offset < 0 ? "-" : "+";
  return `${m[1]}-${m[2]}-${m[3]}T${pad(h)}:${pad(mi)}:00${sign}${pad(Math.trunc(offset / 60))}:${pad(offset % 60)}`;
}
