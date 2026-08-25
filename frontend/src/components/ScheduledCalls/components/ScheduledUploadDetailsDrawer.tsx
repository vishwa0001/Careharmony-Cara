import React from 'react';
import { Calendar, CheckCircle2, FileText, Globe, HardDrive, Hash, Link2, RefreshCw, RotateCcw, X, XCircle } from 'lucide-react';
import type { ScheduledUpload } from '../../../types/scheduledCalls.types';
import { getAvailableActions } from '../../../utils/statusActions';
import { formatDateTimeInZone, getTimezoneOffsetDisplay } from '../../../utils/timezone';
import { StatusBadge } from './StatusBadge';

interface ScheduledUploadDetailsDrawerProps {
  upload: ScheduledUpload | null;
  onClose: () => void;
  onCancelSchedule: (id: string) => void;
  onOpenReschedule: (record: ScheduledUpload) => void;
  onOpenReupload: (record: ScheduledUpload) => void;
}

export const ScheduledUploadDetailsDrawer: React.FC<ScheduledUploadDetailsDrawerProps> = ({
  upload,
  onClose,
  onCancelSchedule,
  onOpenReschedule,
  onOpenReupload,
}) => {
  if (!upload) return null;

  const actions = getAvailableActions(upload.status);
  const checklist = upload.validationSummary?.summaryChecklist;
  const tzOffsetDisplay = getTimezoneOffsetDisplay(upload.timezone);

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-slate-950/70 backdrop-blur-sm flex justify-end animate-in fade-in duration-200">
      <div className="bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-700/80 w-full max-w-lg h-full overflow-y-auto p-6 shadow-2xl space-y-6 flex flex-col justify-between">
        <div className="space-y-6">
          {/* Drawer Header */}
          <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 pb-4">
            <div>
              <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
                File Details
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">Batch ID: {upload.id}</p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="text-slate-400 hover:text-slate-600 dark:hover:text-white p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Status Badge Banner */}
          <div className="bg-slate-50 dark:bg-slate-800/60 p-4 rounded-xl border border-slate-200 dark:border-slate-700/50 flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">Batch Status:</span>
            <StatusBadge status={upload.status} />
          </div>

          {/* Lineage References */}
          {(upload.originalRecordId || upload.rescheduledToId || upload.replacedById) && (
            <div className="bg-indigo-50 dark:bg-indigo-950/30 border border-indigo-200 dark:border-indigo-500/30 rounded-xl p-3.5 space-y-2 text-xs">
              <div className="flex items-center gap-1.5 font-bold text-indigo-900 dark:text-indigo-200">
                <Link2 className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                Batch Lineage & Relationships
              </div>

              {upload.originalRecordId && (
                <p className="text-indigo-800 dark:text-indigo-300">
                  <span className="font-semibold">Linked From: </span>#{upload.originalRecordId}
                </p>
              )}

              {upload.rescheduledToId && (
                <p className="text-indigo-800 dark:text-indigo-300">
                  <span className="font-semibold">Rescheduled To: </span>#{upload.rescheduledToId}
                </p>
              )}

              {upload.replacedById && (
                <p className="text-indigo-800 dark:text-indigo-300">
                  <span className="font-semibold">Replaced By: </span>#{upload.replacedById}
                </p>
              )}
            </div>
          )}

          {/* Core Metadata Table */}
          <div className="space-y-3 text-xs">
            <div className="flex items-center justify-between p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40 border border-slate-200 dark:border-slate-800">
              <span className="text-slate-500 dark:text-slate-400 flex items-center gap-2">
                <FileText className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                File Name:
              </span>
              <span className="font-semibold text-slate-900 dark:text-slate-100 truncate max-w-[220px]">
                {upload.fileName}
              </span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40 border border-slate-200 dark:border-slate-800">
              <span className="text-slate-500 dark:text-slate-400 flex items-center gap-2">
                <HardDrive className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                File Size:
              </span>
              <span className="font-medium text-slate-700 dark:text-slate-200">
                {(upload.fileSize / 1024).toFixed(1)} KB
              </span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40 border border-slate-200 dark:border-slate-800">
              <span className="text-slate-500 dark:text-slate-400 flex items-center gap-2">
                <Hash className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                Customers:
              </span>
              <span className="font-bold text-emerald-600 dark:text-emerald-300">
                {upload.customerCount} records
              </span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40 border border-slate-200 dark:border-slate-800">
              <span className="text-slate-500 dark:text-slate-400 flex items-center gap-2">
                <Calendar className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                Scheduled:
              </span>
              <span className="font-semibold text-slate-900 dark:text-slate-100">
                {formatDateTimeInZone(upload.scheduledAt, upload.timezone)}
              </span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40 border border-slate-200 dark:border-slate-800">
              <span className="text-slate-500 dark:text-slate-400 flex items-center gap-2">
                <Globe className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                Timezone:
              </span>
              <span className="font-medium text-slate-700 dark:text-slate-300">
                {upload.timezone} ({tzOffsetDisplay})
              </span>
            </div>
          </div>

          {/* Failure / Cancellation Reasons */}
          {upload.failureReason && (
            <div className="bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-500/30 rounded-xl p-3.5 space-y-1 text-xs">
              <span className="font-bold text-rose-800 dark:text-rose-300 block">Failure Details:</span>
              <p className="text-rose-700 dark:text-rose-200">{upload.failureReason}</p>
            </div>
          )}

          {upload.cancellationReason && (
            <div className="bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-500/30 rounded-xl p-3.5 space-y-1 text-xs">
              <span className="font-bold text-amber-800 dark:text-amber-300 block">Cancellation Details:</span>
              <p className="text-amber-700 dark:text-amber-200">{upload.cancellationReason}</p>
            </div>
          )}

          {/* Campaign Outcome Summary */}
          {upload.summary && (
            <div className="space-y-3 pt-2">
              <h3 className="text-sm font-bold text-slate-900 dark:text-slate-200 border-b border-slate-200 dark:border-slate-800 pb-2">
                Campaign Outcomes
              </h3>
              <div className="grid grid-cols-2 gap-2 text-xs">
                {[
                  ['Completed', upload.summary.completed],
                  ['Pending', upload.summary.pending],
                  ['In Progress', upload.summary.inProgress],
                  ['Call Setup Failed', upload.summary.callSetupFailed],
                ].map(([label, value]) => (
                  <div key={String(label)} className="p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40 border border-slate-200 dark:border-slate-800">
                    <div className="text-slate-500 dark:text-slate-400">{label}</div>
                    <div className="text-base font-bold text-slate-900 dark:text-slate-100">{value}</div>
                  </div>
                ))}
              </div>
              {Object.keys(upload.summary.dispositions || {}).length > 0 && (
                <div className="space-y-1.5 text-xs">
                  {Object.entries(upload.summary.dispositions).map(([label, count]) => (
                    <div key={label} className="flex items-center justify-between py-1.5 border-b border-slate-100 dark:border-slate-800 last:border-0">
                      <span className="text-slate-600 dark:text-slate-300">{label}</span>
                      <span className="font-semibold text-slate-900 dark:text-slate-100">{count}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {upload.patientResults && upload.patientResults.length > 0 && (
            <div className="space-y-3 pt-2">
              <h3 className="text-sm font-bold text-slate-900 dark:text-slate-200 border-b border-slate-200 dark:border-slate-800 pb-2">
                Patient Results
              </h3>
              <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                {upload.patientResults.map((patient) => (
                  <div key={patient.patientId} className="p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40 border border-slate-200 dark:border-slate-800 text-xs">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-semibold text-slate-900 dark:text-slate-100 truncate">
                        {patient.customerName || patient.patientId}
                      </div>
                      <div className="text-slate-500 dark:text-slate-400">••••{patient.phoneLast4 || ''}</div>
                    </div>
                    <div className="mt-1 text-slate-600 dark:text-slate-300">
                      {patient.disposition || patient.status}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Validation Checklist Summary */}
          <div className="space-y-3 pt-2">
            <h3 className="text-sm font-bold text-slate-900 dark:text-slate-200 border-b border-slate-200 dark:border-slate-800 pb-2">
              Validation Checklist
            </h3>

            {checklist ? (
              <div className="space-y-2 text-xs">
                <div className="flex items-center gap-2 text-slate-700 dark:text-slate-200">
                  {checklist.fileTypeValid ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
                  ) : (
                    <XCircle className="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0" />
                  )}
                  <span>File type valid (.csv)</span>
                </div>

                <div className="flex items-center gap-2 text-slate-700 dark:text-slate-200">
                  {checklist.requiredColumnsPresent ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
                  ) : (
                    <XCircle className="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0" />
                  )}
                  <span>Required Cara campaign columns present</span>
                </div>

                <div className="flex items-center gap-2 text-slate-700 dark:text-slate-200">
                  {checklist.recordsFound ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
                  ) : (
                    <XCircle className="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0" />
                  )}
                  <span>{upload.customerCount} customer records found</span>
                </div>
              </div>
            ) : (
              <p className="text-xs text-slate-500 dark:text-slate-400">No detailed validation checklist saved.</p>
            )}
          </div>
        </div>

        {/* Drawer Footer Actions */}
        <div className="pt-4 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between gap-3">
          {actions.canReschedule && (
            <button
              type="button"
              onClick={() => {
                onClose();
                onOpenReschedule(upload);
              }}
              className="px-3.5 py-2 text-xs font-semibold text-indigo-700 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-600/20 hover:bg-indigo-100 dark:hover:bg-indigo-600/30 border border-indigo-200 dark:border-indigo-500/30 rounded-xl transition-colors flex items-center gap-1.5"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Reschedule
            </button>
          )}

          {actions.canReupload && (
            <button
              type="button"
              onClick={() => {
                onClose();
                onOpenReupload(upload);
              }}
              className="px-3.5 py-2 text-xs font-semibold text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-600/20 hover:bg-amber-100 dark:hover:bg-amber-600/30 border border-amber-200 dark:border-amber-500/30 rounded-xl transition-colors flex items-center gap-1.5"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Re-upload Sheet
            </button>
          )}

          {actions.canCancel && (
            <button
              type="button"
              onClick={() => onCancelSchedule(upload.id)}
              className="px-3.5 py-2 text-xs font-semibold text-rose-700 dark:text-rose-300 bg-rose-50 dark:bg-rose-500/10 hover:bg-rose-100 dark:hover:bg-rose-500/20 border border-rose-200 dark:border-rose-500/30 rounded-xl transition-colors"
            >
              Cancel Schedule
            </button>
          )}

          <button
            type="button"
            onClick={onClose}
            className="ml-auto px-4 py-2 text-xs font-semibold text-slate-700 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 rounded-xl transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
