import React, { useState } from 'react';
import { Calendar, Clock, Globe, Search } from 'lucide-react';
import { CONFIG } from '../../../config/constants';
import { getQuickPresetWallClock, getTimezoneOptions, getTomorrowPresetWallClock } from '../../../utils/timezone';

interface ScheduleDateTimePickerProps {
  scheduleTime: string;
  selectedTimezone: string;
  timeError: string | null;
  onScheduleTimeChange: (dateTimeIso: string) => void;
  onTimezoneChange: (ianaZone: string) => void;
}

export const ScheduleDateTimePicker: React.FC<ScheduleDateTimePickerProps> = ({
  scheduleTime,
  selectedTimezone,
  timeError,
  onScheduleTimeChange,
  onTimezoneChange,
}) => {
  const [tzSearch, setTzSearch] = useState<string>('');
  const timezoneOptions = getTimezoneOptions(tzSearch);

  const formatForInput = (wallClockStr: string): string => {
    if (!wallClockStr) return '';
    return wallClockStr.slice(0, 16);
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onScheduleTimeChange(e.target.value);
  };

  const setQuickTime = (minutesAhead: number) => {
    const presetWallClock = getQuickPresetWallClock(minutesAhead, selectedTimezone);
    onScheduleTimeChange(presetWallClock);
  };

  const setTomorrow = () => {
    const presetWallClock = getTomorrowPresetWallClock(selectedTimezone, scheduleTime);
    onScheduleTimeChange(presetWallClock);
  };

  return (
    <div className="space-y-5">
      {/* Date Time Picker Header */}
      <div className="flex items-center justify-between">
        <label className="text-sm font-semibold text-slate-900 dark:text-slate-200 flex items-center gap-2">
          <Clock className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
          Schedule Calling Time
        </label>
      </div>

      <div className="grid grid-cols-1 gap-4">
        {/* Date Time Input */}
        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">
            Date & Time
          </label>
          <input
            type="datetime-local"
            value={formatForInput(scheduleTime)}
            onChange={handleChange}
            className={`w-full bg-white dark:bg-slate-800/90 border rounded-xl px-4 py-2.5 text-xs text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 transition-all ${
              timeError
                ? 'border-rose-500/80 focus:ring-rose-500/30'
                : 'border-slate-300 dark:border-slate-700 focus:border-indigo-500 focus:ring-indigo-500/20'
            }`}
          />
        </div>

        {/* Timezone Selector */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label className="text-xs font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-1">
              <Globe className="w-3.5 h-3.5 text-indigo-600 dark:text-indigo-400" />
              Timezone (Required)
            </label>
          </div>

          <div className="space-y-2">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                placeholder="Search timezone (e.g. Kolkata, New York, UTC)..."
                value={tzSearch}
                onChange={(e) => setTzSearch(e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs text-slate-800 dark:text-slate-200 placeholder-slate-400 focus:outline-none focus:border-indigo-500"
              />
            </div>

            <select
              value={selectedTimezone}
              onChange={(e) => onTimezoneChange(e.target.value)}
              className="w-full bg-white dark:bg-slate-800/90 border border-slate-300 dark:border-slate-700 rounded-xl px-4 py-2.5 text-xs text-slate-900 dark:text-slate-100 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
            >
              {timezoneOptions.map((opt) => (
                <option key={opt.iana} value={opt.iana}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Quick Time Preset Buttons */}
      <div className="flex items-center gap-2 pt-1 flex-wrap">
        <span className="text-xs text-slate-500 dark:text-slate-400">Quick select:</span>
        <button
          type="button"
          onClick={() => setQuickTime(15)}
          className="px-2.5 py-1 text-xs bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-md border border-slate-200 dark:border-slate-700 transition-colors"
        >
          +15 Mins
        </button>
        <button
          type="button"
          onClick={() => setQuickTime(60)}
          className="px-2.5 py-1 text-xs bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-md border border-slate-200 dark:border-slate-700 transition-colors"
        >
          +1 Hour
        </button>
        <button
          type="button"
          onClick={setTomorrow}
          className="px-2.5 py-1 text-xs bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-md border border-slate-200 dark:border-slate-700 transition-colors"
        >
          Tomorrow
        </button>
      </div>

      {/* Error / Hint feedback */}
      {timeError && (
        <p className="text-xs font-medium text-rose-600 dark:text-rose-400 flex items-center gap-1.5">
          <Calendar className="w-3.5 h-3.5 shrink-0" />
          {timeError}
        </p>
      )}

      {!timeError && (
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Must be scheduled at least {CONFIG.MIN_SCHEDULE_LEAD_TIME_MINUTES} minutes in advance.
        </p>
      )}
    </div>
  );
};