import React, { useState } from 'react';
import { AlertOctagon, ChevronDown, ChevronUp, FileX2 } from 'lucide-react';
import type { ValidationSummary } from '../../../types/scheduledCalls.types';

interface ValidationSummaryCalloutProps {
  summary: ValidationSummary | null;
}

export const ValidationSummaryCallout: React.FC<ValidationSummaryCalloutProps> = ({
  summary,
}) => {
  const [isExpanded, setIsExpanded] = useState<boolean>(true);

  if (!summary || summary.isValid) {
    return null;
  }

  const fatalErrors = summary.errors.filter((e) => e.type === 'FATAL');

  return (
    <div className="bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-500/40 rounded-xl overflow-hidden text-xs">
      {/* Summary Header */}
      <div className="p-4 bg-rose-100/60 dark:bg-rose-900/30 flex items-center justify-between gap-3 border-b border-rose-200 dark:border-rose-500/20">
        <div className="flex items-center gap-2.5 text-rose-800 dark:text-rose-300 font-semibold">
          <AlertOctagon className="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0" />
          <span>
            {fatalErrors.length} validation error{fatalErrors.length === 1 ? '' : 's'} found in sheet
          </span>
        </div>

        <button
          type="button"
          onClick={() => setIsExpanded((prev) => !prev)}
          className="text-rose-700 dark:text-rose-400 hover:text-rose-900 dark:hover:text-rose-200 flex items-center gap-1 font-medium text-xs transition-colors"
        >
          {isExpanded ? (
            <>
              Hide Details <ChevronUp className="w-3.5 h-3.5" />
            </>
          ) : (
            <>
              View {fatalErrors.length} Error{fatalErrors.length === 1 ? '' : 's'}{' '}
              <ChevronDown className="w-3.5 h-3.5" />
            </>
          )}
        </button>
      </div>

      {/* Row by row error list */}
      {isExpanded && (
        <div className="p-4 space-y-2 max-h-48 overflow-y-auto divide-y divide-rose-200 dark:divide-rose-500/10">
          {fatalErrors.map((err, idx) => (
            <div key={idx} className="pt-2 first:pt-0 flex items-start gap-2 text-rose-900 dark:text-rose-200">
              <FileX2 className="w-3.5 h-3.5 text-rose-600 dark:text-rose-400 shrink-0 mt-0.5" />
              <div>
                {err.row && <span className="font-bold text-rose-700 dark:text-rose-300">Row {err.row}: </span>}
                <span>{err.message}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
