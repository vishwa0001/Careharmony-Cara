import React, { useState } from 'react';
import { CalendarClock, FileText, Globe, Loader2, RotateCcw, Search, Users, X } from 'lucide-react';
import type { ScheduledUpload } from '../../../types/scheduledCalls.types';
import { formatDateTimeInZone, getDefaultTimezone, getTimezoneOptions, localDateTimeInZoneToUtc } from '../../../utils/timezone';
import { validateScheduleTime } from '../../../utils/scheduledCalls.validation';

interface RescheduleModalProps {
  isOpen: boolean;
  targetRecord: ScheduledUpload | null;
  isSubmitting: boolean;
  onClose: () => void;
  onConfirmReschedule: (id: string, newScheduleTime: string, timezone: string) => Promise<void>;
}

export const RescheduleModal: React.FC<RescheduleModalProps> = ({
  isOpen,
  targetRecord,
  isSubmitting,
  onClose,
  onConfirmReschedule,
}) => {
  if (!isOpen || !targetRecord) return null;

  const [newScheduleTime, setNewScheduleTime] = useState<string>('');
  const [selectedTimezone, setSelectedTimezone] = useState<string>(
    targetRecord.timezone || getDefaultTimezone()
  );
  const [timeError, setTimeError] = useState<string | null>(null);
  const [tzSearch, setTzSearch] = useState<string>('');

  const timezoneOptions = getTimezoneOptions(tzSearch);

  const handleTimeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const rawVal = e.target.value;
    setNewScheduleTime(rawVal);
    if (!rawVal) {
      setTimeError('Please select a new schedule time.');
      return;
    }
    const check = validateScheduleTime(rawVal, selectedTimezone);
    setTimeError(check.isValid ? null : check.error || 'Invalid schedule time.');
  };

  const handleFormSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newScheduleTime) {
      setTimeError('Please select a new schedule time.');
      return;
    }
    const check = validateScheduleTime(newScheduleTime, selectedTimezone);
    if (!check.isValid) {
      setTimeError(check.error || 'Invalid schedule time.');
      return;
    }

    const targetUtcDate = localDateTimeInZoneToUtc(newScheduleTime, selectedTimezone);
    const scheduledAtIso = targetUtcDate && !isNaN(targetUtcDate.getTime())
      ? targetUtcDate.toISOString()
      : newScheduleTime;

    await onConfirmReschedule(targetRecord.id, scheduledAtIso, selectedTimezone);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 pb-4">
          <div className="flex items-center gap-2.5 text-slate-900 dark:text-slate-100 font-bold text-lg">
            <RotateCcw className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
            Reschedule Calling Batch
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-white p-1 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Previous Record Summary */}
        <div className="bg-slate-50 dark:bg-slate-800/60 p-4 rounded-xl border border-slate-200 dark:border-slate-700/60 space-y-2 text-xs">
          <div className="flex items-center justify-between">
            <span className="text-slate-500 dark:text-slate-400 flex items-center gap-2">
              <FileText className="w-4 h-4 text-indigo-500" /> File:
            </span>
            <span className="font-semibold text-slate-900 dark:text-slate-100 truncate max-w-[220px]">
              {targetRecord.fileName}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-slate-500 dark:text-slate-400 flex items-center gap-2">
              <Users className="w-4 h-4 text-emerald-500" /> Customers:
            </span>
            <span className="font-bold text-emerald-600 dark:text-emerald-400">
              {targetRecord.customerCount} records
            </span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-slate-500 dark:text-slate-400 flex items-center gap-2">
              <CalendarClock className="w-4 h-4 text-indigo-500" /> Previous Schedule:
            </span>
            <span className="font-medium text-slate-700 dark:text-slate-300">
              {formatDateTimeInZone(targetRecord.scheduledAt, targetRecord.timezone)}
            </span>
          </div>
        </div>

        {/* Form Inputs */}
        <form onSubmit={handleFormSubmit} className="space-y-4">
          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-700 dark:text-slate-200 flex items-center gap-1.5">
              <CalendarClock className="w-4 h-4 text-indigo-500" />
              New Calling Date & Time
            </label>
            <input
              type="datetime-local"
              required
              onChange={handleTimeChange}
              className="w-full bg-slate-50 dark:bg-slate-800/90 border border-slate-300 dark:border-slate-700 rounded-xl px-4 py-2.5 text-xs text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
            />
            {timeError && <p className="text-xs text-rose-500 font-medium">{timeError}</p>}
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-700 dark:text-slate-200 flex items-center gap-1.5">
              <Globe className="w-4 h-4 text-indigo-500" />
              Timezone
            </label>
            <div className="relative mb-1">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                placeholder="Search timezone..."
                value={tzSearch}
                onChange={(e) => setTzSearch(e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs text-slate-800 dark:text-slate-200 placeholder-slate-400 focus:outline-none focus:border-indigo-500"
              />
            </div>
            <select
              value={selectedTimezone}
              onChange={(e) => setSelectedTimezone(e.target.value)}
              className="w-full bg-slate-50 dark:bg-slate-800/90 border border-slate-300 dark:border-slate-700 rounded-xl px-4 py-2.5 text-xs text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
            >
              {timezoneOptions.map((opt) => (
                <option key={opt.iana} value={opt.iana}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-200 dark:border-slate-800">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="px-4 py-2 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-xl transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting || !!timeError || !newScheduleTime}
              className="px-5 py-2 text-xs font-bold text-white bg-indigo-600 hover:bg-indigo-500 rounded-xl shadow-md shadow-indigo-600/20 flex items-center gap-2 transition-colors disabled:opacity-50"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Rescheduling...
                </>
              ) : (
                'Reschedule Calls'
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};