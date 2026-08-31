export interface TimezoneOption {
  iana: string;
  label: string;
  offsetDisplay: string;
}

const FALLBACK_TIMEZONES = [
  'Asia/Kolkata',
  'America/New_York',
  'America/Los_Angeles',
  'America/Chicago',
  'Europe/London',
  'Europe/Paris',
  'Asia/Dubai',
  'Asia/Singapore',
  'Asia/Tokyo',
  'Australia/Sydney',
  'UTC',
];

/**
 * Gets list of supported IANA timezone identifiers.
 */
export function getSupportedTimezones(): string[] {
  try {
    if (typeof Intl !== 'undefined' && 'supportedValuesOf' in Intl) {
      // @ts-ignore - Intl.supportedValuesOf is supported in Node 18+ and modern browsers
      const list = Intl.supportedValuesOf('timeZone') as string[];
      if (list && list.length > 0) return list;
    }
  } catch (err) {
    // Fallback
  }
  return FALLBACK_TIMEZONES;
}

/**
 * Formats a given date in an IANA timezone to calculate current UTC offset string e.g. "UTC+05:30" or "UTC-04:00".
 */
export function getTimezoneOffsetDisplay(ianaZone: string, date: Date = new Date()): string {
  try {
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: ianaZone,
      timeZoneName: 'shortOffset',
    });
    const parts = formatter.formatToParts(date);
    const tzPart = parts.find((p) => p.type === 'timeZoneName');
    if (tzPart && tzPart.value) {
      let raw = tzPart.value.replace('GMT', 'UTC'); // e.g. UTC+5:30 or UTC-4
      // Normalize single digit hours/minutes to standard HH:mm format if needed
      if (/^UTC[\+\-]\d{1,2}$/.test(raw)) {
        raw = raw.replace(/^UTC([\+\-])(\d)$/, 'UTC$10$2:00').replace(/^UTC([\+\-])(\d{2})$/, 'UTC$1$2:00');
      } else if (/^UTC[\+\-]\d{1,2}:\d{2}$/.test(raw)) {
        raw = raw.replace(/^UTC([\+\-])(\d):(\d{2})$/, 'UTC$10$2:$3');
      }
      return raw;
    }
  } catch (err) {
    // Fallback
  }
  return 'UTC+00:00';
}

/**
 * Generates human-friendly option objects for timezone dropdown.
 */
export function getTimezoneOptions(searchQuery = ''): TimezoneOption[] {
  const allZones = getSupportedTimezones();
  const lowerSearch = searchQuery.toLowerCase();

  const options: TimezoneOption[] = [];

  for (const iana of allZones) {
    const offset = getTimezoneOffsetDisplay(iana);
    const label = `${iana} (${offset})`;

    if (!searchQuery || iana.toLowerCase().includes(lowerSearch) || offset.toLowerCase().includes(lowerSearch)) {
      options.push({
        iana,
        label,
        offsetDisplay: offset,
      });
    }
  }

  // Priority timezones at top when no search query
  if (!searchQuery) {
    const priorityList = ['Asia/Kolkata', 'America/New_York', 'America/Los_Angeles', 'Europe/London', 'Asia/Dubai', 'UTC'];
    options.sort((a, b) => {
      const idxA = priorityList.indexOf(a.iana);
      const idxB = priorityList.indexOf(b.iana);
      if (idxA !== -1 && idxB !== -1) return idxA - idxB;
      if (idxA !== -1) return -1;
      if (idxB !== -1) return 1;
      return a.iana.localeCompare(b.iana);
    });
  }

  return options;
}

/**
 * Detects system browser timezone or falls back to Asia/Kolkata.
 */
export function getDefaultTimezone(): string {
  try {
    const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (detected) return detected;
  } catch (err) {
    // Ignore
  }
  return 'Asia/Kolkata';
}

/**
 * Formats a given date string with its assigned IANA timezone for user display.
 */
export function formatDateTimeInZone(isoStr: string, ianaZone: string): string {
  if (!isoStr) return '-';
  const d = new Date(isoStr);
  if (isNaN(d.getTime())) return '-';

  try {
    return d.toLocaleString('en-IN', {
      timeZone: ianaZone,
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
    });
  } catch (err) {
    return d.toLocaleString();
  }
}

/**
 * Converts a datetime-local wall-clock value ("YYYY-MM-DDTHH:mm") in an IANA timezone to a UTC Date.
 * Bypasses native JS browser parsing completely.
 * Validates DST non-existence (e.g. spring forward gap) and returns invalid Date if time does not exist.
 */
export function localDateTimeInZoneToUtc(localDateTime: string, ianaZone: string): Date {
  const match = localDateTime.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/);
  if (!match) return new Date(NaN);
  const [, yStr, mStr, dStr, hhStr, mmStr, ssStr = '00'] = match;
  const y = +yStr;
  const m = +mStr;
  const d = +dStr;
  const hh = +hhStr;
  const mm = +mmStr;
  const ss = +ssStr;

  const wallAsUtcMs = Date.UTC(y, m - 1, d, hh, mm, ss);

  const getPartsInZone = (instantMs: number) => {
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: ianaZone,
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hourCycle: 'h23',
    });
    const parts = formatter.formatToParts(new Date(instantMs));
    const get = (type: Intl.DateTimeFormatPartTypes) => Number(parts.find((p) => p.type === type)?.value || 0);
    return {
      year: get('year'),
      month: get('month'),
      day: get('day'),
      hour: get('hour'),
      minute: get('minute'),
      second: get('second'),
    };
  };

  const offsetAt = (instantMs: number): number => {
    const p = getPartsInZone(instantMs);
    const representedAsUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
    return representedAsUtc - instantMs;
  };

  try {
    const offset = offsetAt(wallAsUtcMs);
    let utcMs = wallAsUtcMs - offset;
    const refinedOffset = offsetAt(utcMs);
    if (refinedOffset !== offset) {
      utcMs = wallAsUtcMs - refinedOffset;
    }

    // DST non-existence validation:
    // Format computed UTC instant back in ianaZone and check if it matches the target wall-clock numbers.
    const resParts = getPartsInZone(utcMs);
    if (
      resParts.year !== y ||
      resParts.month !== m ||
      resParts.day !== d ||
      resParts.hour !== hh ||
      resParts.minute !== mm
    ) {
      // Wall-clock time does not exist in this timezone (e.g. spring forward gap)
      return new Date(NaN);
    }

    return new Date(utcMs);
  } catch {
    return new Date(NaN);
  }
}

/**
 * Returns wall-clock string "YYYY-MM-DDTHH:mm" for a Date in a specific IANA timezone.
 */
export function getWallClockInZone(date: Date, ianaZone: string): string {
  if (isNaN(date.getTime())) return '';
  try {
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: ianaZone,
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
      hourCycle: 'h23',
    });
    const parts = formatter.formatToParts(date);
    const get = (type: Intl.DateTimeFormatPartTypes) => {
      const val = parts.find((p) => p.type === type)?.value || '0';
      return val.padStart(2, '0');
    };
    return `${get('year')}-${get('month')}-${get('day')}T${get('hour')}:${get('minute')}`;
  } catch {
    return '';
  }
}

/**
 * Calculates a quick time preset relative to current instant in the target IANA timezone.
 */
export function getQuickPresetWallClock(minutesAhead: number, ianaZone: string, baseDate = new Date()): string {
  const targetDate = new Date(baseDate.getTime() + minutesAhead * 60 * 1000);
  const rawWall = getWallClockInZone(targetDate, ianaZone);
  if (!rawWall) return '';
  // Round minutes to nearest 5 mins
  const match = rawWall.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})$/);
  if (!match) return rawWall;
  const [, datePart, hhStr, mmStr] = match;
  let mm = Math.ceil(+mmStr / 5) * 5;
  let hh = +hhStr;
  if (mm >= 60) {
    mm = 0;
    hh = (hh + 1) % 24;
  }
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${datePart}T${pad(hh)}:${pad(mm)}`;
}

/**
 * Calculates 'Tomorrow' preset as the next calendar day in the target IANA timezone.
 */
export function getTomorrowPresetWallClock(ianaZone: string, currentWallClock?: string): string {
  const nowWall = getWallClockInZone(new Date(), ianaZone);
  if (!nowWall) return '';

  const match = (currentWallClock && currentWallClock.includes('T')) ? currentWallClock.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/) : nowWall.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/);
  if (!match) return '';
  const [, yStr, mStr, dStr, hhStr, mmStr] = match;

  // Advance 1 calendar day
  const d = new Date(Date.UTC(+yStr, +mStr - 1, +dStr + 1));
  const pad = (n: number) => String(n).padStart(2, '0');
  const nextDatePart = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
  return `${nextDatePart}T${hhStr}:${mmStr}`;
}