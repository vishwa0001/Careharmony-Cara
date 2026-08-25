import React from 'react';
import { AlertCircle, Calendar, FileText, Globe, Loader2, Users, X } from 'lucide-react';
import { formatDateTimeInZone, getTimezoneOffsetDisplay } from '../../../utils/timezone';

interface ScheduleConfirmationModalProps {
  isOpen: boolean;
  fileName: string;
  customerCount: number;
  scheduleTime: string;
  timezone: string;
  isSubmitting: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export const ScheduleConfirmationModal: React.FC<ScheduleConfirmationModalProps> = ({
  isOpen,
  fileName,
  customerCount,
  scheduleTime,
  timezone,
  isSubmitting,
  onClose,
  onConfirm,
}) => {
  if (!isOpen) return null;

  const tzOffsetDisplay = getTimezoneOffsetDisplay(timezone);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700/80 rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-6">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 pb-4">
          <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100 font-bold text-lg">
            <AlertCircle className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
            Confirm Calling Schedule
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-white p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body / Summary Cards */}
        <div className="space-y-3 text-sm">
          <div className="bg-slate-50 dark:bg-slate-800/60 p-3.5 rounded-xl border border-slate-200 dark:border-slate-700/50 flex items-center justify-between">
            <div className="flex items-center gap-2.5 text-slate-500 dark:text-slate-400">
              <FileText className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
              <span>File Name:</span>
            </div>
            <span className="font-semibold text-slate-900 dark:text-slate-100 truncate max-w-[200px]">
              {fileName}
            </span>
          </div>

          <div className="bg-slate-50 dark:bg-slate-800/60 p-3.5 rounded-xl border border-slate-200 dark:border-slate-700/50 flex items-center justify-between">
            <div className="flex items-center gap-2.5 text-slate-500 dark:text-slate-400">
              <Users className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              <span>Customers:</span>
            </div>
            <span className="font-bold text-emerald-600 dark:text-emerald-300">{customerCount} Records</span>
          </div>

          <div className="bg-slate-50 dark:bg-slate-800/60 p-3.5 rounded-xl border border-slate-200 dark:border-slate-700/50 flex items-center justify-between">
            <div className="flex items-center gap-2.5 text-slate-500 dark:text-slate-400">
              <Calendar className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
              <span>Scheduled Time:</span>
            </div>
            <span className="font-semibold text-slate-900 dark:text-slate-100">
              {formatDateTimeInZone(scheduleTime, timezone)}
            </span>
          </div>

          <div className="bg-slate-50 dark:bg-slate-800/60 p-3.5 rounded-xl border border-slate-200 dark:border-slate-700/50 flex items-center justify-between">
            <div className="flex items-center gap-2.5 text-slate-500 dark:text-slate-400">
              <Globe className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
              <span>Timezone:</span>
            </div>
            <span className="font-medium text-slate-700 dark:text-slate-300">
              {timezone} ({tzOffsetDisplay})
            </span>
          </div>
        </div>

        <p className="text-xs text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/40 p-3 rounded-lg border border-slate-200 dark:border-slate-800">
          Submitting will queue this batch for automated outbound call execution at the selected scheduled time.
        </p>

        {/* Modal Actions */}
        <div className="flex items-center justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="px-4 py-2.5 text-xs font-semibold text-slate-700 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 rounded-xl transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isSubmitting}
            className="px-5 py-2.5 text-xs font-bold text-white bg-indigo-600 hover:bg-indigo-500 rounded-xl shadow-lg shadow-indigo-600/30 flex items-center gap-2 transition-all disabled:opacity-50"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Scheduling...
              </>
            ) : (
              'Confirm & Schedule'
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
