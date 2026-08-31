import React, { useState } from 'react';
import { CalendarClock, Globe, Loader2, RefreshCw, X } from 'lucide-react';
import type { ScheduledUpload, ValidationSummary } from '../../../types/scheduledCalls.types';
import { scheduledCallsService } from '../../../services/scheduledCalls.service';
import { getDefaultTimezone, getTimezoneOptions, localDateTimeInZoneToUtc } from '../../../utils/timezone';
import { validateFileMetadata, validateScheduleTime } from '../../../utils/scheduledCalls.validation';
import { CustomerSheetUpload } from './CustomerSheetUpload';
import { ValidationSummaryCallout } from './ValidationSummaryCallout';

interface ReuploadModalProps {
  isOpen: boolean;
  targetRecord: ScheduledUpload | null;
  isSubmitting: boolean;
  onClose: () => void;
  onConfirmReupload: (
    id: string,
    file: File,
    scheduleTime: string,
    timezone: string,
    customerCount: number,
    validationSummary: ValidationSummary
  ) => Promise<void>;
}

export const ReuploadModal: React.FC<ReuploadModalProps> = ({
  isOpen,
  targetRecord,
  isSubmitting,
  onClose,
  onConfirmReupload,
}) => {
  if (!isOpen || !targetRecord) return null;

  const [replacementFile, setReplacementFile] = useState<File | null>(null);
  const [isParsing, setIsParsing] = useState<boolean>(false);
  const [validationSummary, setValidationSummary] = useState<ValidationSummary | null>(null);
  const [newScheduleTime, setNewScheduleTime] = useState<string>('');
  const [selectedTimezone, setSelectedTimezone] = useState<string>(
    targetRecord.timezone || getDefaultTimezone()
  );
  const [timeError, setTimeError] = useState<string | null>(null);

  const timezoneOptions = getTimezoneOptions();

  const handleFileSelect = async (file: File | null) => {
    setReplacementFile(file);
    setValidationSummary(null);

    if (!file) return;

    const metaCheck = validateFileMetadata(file);
    if (!metaCheck.isValid) return;

    try {
      setIsParsing(true);
      const summary = await scheduledCallsService.validateCustomerSheet(file);
      setValidationSummary(summary);
    } catch (err) {
      // Error handled
    } finally {
      setIsParsing(false);
    }
  };

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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!replacementFile || !validationSummary || !validationSummary.isValid || !newScheduleTime) {
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

    await onConfirmReupload(
      targetRecord.id,
      replacementFile,
      scheduledAtIso,
      selectedTimezone,
      validationSummary.totalRows,
      validationSummary
    );

    onClose();
  };

  const isFormValid =
    replacementFile &&
    validationSummary &&
    validationSummary.isValid &&
    newScheduleTime &&
    !timeError;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl max-w-xl w-full p-6 shadow-2xl space-y-6 max-h-[90vh] overflow-y-auto">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 pb-4">
          <div>
            <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <RefreshCw className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
              Re-upload Replacement Sheet
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Replacing failed batch: <span className="font-semibold">{targetRecord.fileName}</span> (#{targetRecord.id})
            </p>
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

        {/* Upload Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* File Dropzone */}
          <CustomerSheetUpload
            selectedFile={replacementFile}
            isParsing={isParsing}
            metaErrors={[]}
            metaWarnings={[]}
            validationSummary={validationSummary}
            onFileSelect={handleFileSelect}
          />

          {/* Validation Summary Callout */}
          <ValidationSummaryCallout summary={validationSummary} />

          {/* Schedule Time & Timezone Inputs */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-xs font-semibold text-slate-700 dark:text-slate-200 flex items-center gap-1.5">
                <CalendarClock className="w-4 h-4 text-indigo-500" />
                Calling Date & Time
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
          </div>

          {/* Footer Actions */}
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
              disabled={!isFormValid || isSubmitting}
              className="px-5 py-2 text-xs font-bold text-white bg-indigo-600 hover:bg-indigo-500 rounded-xl shadow-md shadow-indigo-600/20 flex items-center gap-2 transition-colors disabled:opacity-50"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Scheduling...
                </>
              ) : (
                'Schedule Replacement Batch'
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};