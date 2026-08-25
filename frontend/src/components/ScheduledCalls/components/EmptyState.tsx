import React from 'react';
import { CalendarX2, UploadCloud } from 'lucide-react';

interface EmptyStateProps {
  onActionClick: () => void;
}

export const EmptyState: React.FC<EmptyStateProps> = ({ onActionClick }) => {
  return (
    <div className="text-center py-12 px-4 bg-white dark:bg-slate-900/40 border border-slate-200 dark:border-slate-800 rounded-2xl space-y-4 shadow-sm">
      <div className="w-14 h-14 rounded-full bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-400 flex items-center justify-center mx-auto">
        <CalendarX2 className="w-7 h-7 text-indigo-600 dark:text-indigo-400" />
      </div>

      <div className="max-w-sm mx-auto space-y-1">
        <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">No scheduled calls yet</h3>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Upload a customer sheet and choose a time to schedule your first calling batch.
        </p>
      </div>

      <button
        type="button"
        onClick={onActionClick}
        className="inline-flex items-center gap-2 px-4 py-2.5 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 rounded-xl transition-all shadow-md shadow-indigo-600/20"
      >
        <UploadCloud className="w-4 h-4" />
        Upload Customer Sheet
      </button>
    </div>
  );
};
