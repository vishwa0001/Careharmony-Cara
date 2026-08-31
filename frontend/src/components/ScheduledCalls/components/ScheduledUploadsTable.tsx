import React, { useState } from 'react';
import { Calendar, Download, Eye, FileText, Filter, Loader2, RefreshCw, RotateCcw, Search, XCircle } from 'lucide-react';
import type { ScheduledUpload } from '../../../types/scheduledCalls.types';
import { scheduledCallsService } from '../../../services/scheduledCalls.service';
import { getAvailableActions } from '../../../utils/statusActions';
import { formatDateTimeInZone } from '../../../utils/timezone';
import { EmptyState } from './EmptyState';
import { StatusBadge } from './StatusBadge';
import { Tooltip } from './Tooltip';

const EXPORTABLE_STATUSES = ["COMPLETED", "PARTIAL", "FAILED", "CALL_SETUP_FAILED", "CALLBACK_SCHEDULED", "PROCESSING"];

interface ScheduledUploadsTableProps {
  uploads: ScheduledUpload[];
  totalCount: number;
  isLoading: boolean;
  searchQuery: string;
  statusFilter: string;
  onSearchChange: (query: string) => void;
  onFilterChange: (status: string) => void;
  onViewDetails: (id: string) => void;
  onOpenReschedule: (record: ScheduledUpload) => void;
  onOpenReupload: (record: ScheduledUpload) => void;
  onCancelSchedule: (id: string) => void;
  onEmptyAction: () => void;
}

export const ScheduledUploadsTable: React.FC<ScheduledUploadsTableProps> = ({
  uploads,
  totalCount,
  isLoading,
  searchQuery,
  statusFilter,
  onSearchChange,
  onFilterChange,
  onViewDetails,
  onOpenReschedule,
  onOpenReupload,
  onCancelSchedule,
  onEmptyAction,
}) => {
  const [downloadingIds, setDownloadingIds] = useState<Set<string>>(new Set());

  const handleDownloadCsv = async (id: string, fileName: string) => {
    try {
      setDownloadingIds((prev) => new Set(prev).add(id));
      await scheduledCallsService.downloadCampaignCsv(id, fileName);
    } catch (err: any) {
      console.error('Download CSV failed:', err);
      alert(err.message || 'Failed to download CSV');
    } finally {
      setDownloadingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  return (
    <div className="space-y-4">
      {/* Table Title and Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
            Scheduled Uploads
            <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700 font-semibold">
              {uploads.length}
            </span>
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Overview of scheduled, executing, and completed customer call batches
          </p>
        </div>

        {/* Search & Status Filter */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 sm:flex-initial min-w-[200px]">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search filename..."
              value={searchQuery}
              onChange={(e) => onSearchChange(e.target.value)}
              className="w-full pl-9 pr-4 py-2 bg-white dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700/80 rounded-xl text-xs text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          <div className="relative">
            <Filter className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <select
              value={statusFilter}
              onChange={(e) => onFilterChange(e.target.value)}
              className="pl-8 pr-8 py-2 bg-white dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700/80 rounded-xl text-xs text-slate-800 dark:text-slate-200 focus:outline-none focus:border-indigo-500 appearance-none cursor-pointer"
            >
              <option value="ALL">All Statuses</option>
              <option value="SCHEDULED">Scheduled</option>
              <option value="PROCESSING">Processing</option>
              <option value="COMPLETED">Completed</option>
              <option value="FAILED">Failed</option>
              <option value="VALIDATION_FAILED">Validation Failed</option>
              <option value="CANCELLED">Cancelled</option>
            </select>
          </div>
        </div>
      </div>

      {/* Table Container */}
      {isLoading ? (
        <div className="py-16 text-center text-slate-500 dark:text-slate-400 flex flex-col items-center gap-3 bg-white dark:bg-slate-900/40 border border-slate-200 dark:border-slate-800 rounded-2xl">
          <Loader2 className="w-6 h-6 animate-spin text-indigo-600 dark:text-indigo-400" />
          <span className="text-xs">Loading scheduled uploads...</span>
        </div>
      ) : totalCount === 0 ? (
        <EmptyState onActionClick={onEmptyAction} />
      ) : uploads.length === 0 ? (
        <div className="py-12 text-center text-slate-500 dark:text-slate-400 bg-white dark:bg-slate-900/40 border border-slate-200 dark:border-slate-800 rounded-2xl text-xs">
          No uploads match your search or filter criteria.
        </div>
      ) : (
        <div className="bg-white dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 rounded-2xl overflow-hidden shadow-sm dark:shadow-xl">
          {/* Desktop Table View */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 font-semibold uppercase tracking-wider">
                  <th className="py-3.5 px-4">File Name</th>
                  <th className="py-3.5 px-4 text-right">Customers</th>
                  <th className="py-3.5 px-4">Scheduled Time</th>
                  <th className="py-3.5 px-4">Status</th>
                  <th className="py-3.5 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 text-slate-800 dark:text-slate-200">
                {uploads.map((row) => {
                  const actions = getAvailableActions(row.status);
                  const isRowDownloading = downloadingIds.has(row.id);
                  const statusStr = String(row.status || '');
                  const isExportable = EXPORTABLE_STATUSES.includes(statusStr);
                  const exportTooltip = isExportable
                    ? "Download call results as CSV"
                    : statusStr === "UPLOAD_PENDING" || statusStr === "UPLOADED"
                      ? "Campaign is still being processed, export will be available once calls are scheduled"
                      : statusStr === "PENDING" || statusStr === "SCHEDULED"
                        ? "No calls have been made yet, export will be available after calls are completed"
                        : "Export is not available for this campaign status";

                  return (
                    <tr key={row.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors">
                      <td className="py-4 px-4 font-medium">
                        <div className="flex items-center gap-2.5">
                          <FileText className="w-4 h-4 text-indigo-600 dark:text-indigo-400 shrink-0" />
                          <div className="min-w-0">
                            <p className="truncate max-w-[200px]" title={row.fileName}>
                              {row.fileName}
                            </p>
                            {row.originalRecordId && (
                              <span className="text-[10px] text-indigo-600 dark:text-indigo-400 font-mono">
                                Linked from #{row.originalRecordId}
                              </span>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="py-4 px-4 text-right font-semibold text-emerald-600 dark:text-emerald-300">
                        {row.customerCount}
                      </td>
                      <td className="py-4 px-4 text-slate-600 dark:text-slate-300">
                        <div className="flex items-center gap-1.5">
                          <Calendar className="w-3.5 h-3.5 text-indigo-600 dark:text-indigo-400 shrink-0" />
                          <span>{formatDateTimeInZone(row.scheduledAt, row.timezone)}</span>
                        </div>
                      </td>
                      <td className="py-4 px-4">
                        <StatusBadge status={row.status} />
                      </td>
                      <td className="py-4 px-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <Tooltip content={exportTooltip}>
                            <span>
                              <button
                                type="button"
                                disabled={!isExportable || isRowDownloading}
                                onClick={() => (!isExportable || isRowDownloading) ? undefined : handleDownloadCsv(row.id, row.fileName)}
                                className={`inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-semibold text-indigo-700 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-900/40 border border-indigo-300 dark:border-indigo-500/30 rounded-lg transition-colors shrink-0 ${
                                  !isExportable
                                    ? "opacity-50 cursor-not-allowed"
                                    : "hover:text-indigo-900 dark:hover:text-white hover:bg-indigo-100 dark:hover:bg-indigo-800/60"
                                }`}
                              >
                                {isRowDownloading ? (
                                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                ) : (
                                  <Download className="w-3.5 h-3.5" />
                                )}
                                <span>CSV</span>
                              </button>
                            </span>
                          </Tooltip>

                          {actions.canView && (
                            <button
                              type="button"
                              onClick={() => onViewDetails(row.id)}
                              className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-semibold text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 border border-slate-200 dark:border-slate-700 rounded-lg transition-colors"
                            >
                              <Eye className="w-3.5 h-3.5 text-indigo-600 dark:text-indigo-400" />
                              View
                            </button>
                          )}

                          {actions.canReschedule && (
                            <button
                              type="button"
                              onClick={() => onOpenReschedule(row)}
                              className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-semibold text-indigo-700 dark:text-indigo-300 hover:bg-indigo-100 dark:hover:bg-indigo-600/30 bg-indigo-50 dark:bg-indigo-600/20 border border-indigo-200 dark:border-indigo-500/30 rounded-lg transition-colors"
                            >
                              <RotateCcw className="w-3.5 h-3.5" />
                              Reschedule
                            </button>
                          )}

                          {actions.canReupload && (
                            <button
                              type="button"
                              onClick={() => onOpenReupload(row)}
                              className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-semibold text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-600/30 bg-amber-50 dark:bg-amber-600/20 border border-amber-200 dark:border-amber-500/30 rounded-lg transition-colors"
                            >
                              <RefreshCw className="w-3.5 h-3.5" />
                              Re-upload
                            </button>
                          )}

                          {actions.canCancel && (
                            <button
                              type="button"
                              onClick={() => onCancelSchedule(row.id)}
                              className="p-1.5 text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-500/20 rounded-lg transition-colors"
                              title="Cancel Schedule"
                            >
                              <XCircle className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Mobile Card List View */}
          <div className="md:hidden divide-y divide-slate-200 dark:divide-slate-800 p-2">
            {uploads.map((row) => {
              const actions = getAvailableActions(row.status);
              const isRowDownloading = downloadingIds.has(row.id);
              const statusStr = String(row.status || '');
              const isExportable = EXPORTABLE_STATUSES.includes(statusStr);
              const exportTooltip = isExportable
                ? "Download call results as CSV"
                : statusStr === "UPLOAD_PENDING" || statusStr === "UPLOADED"
                  ? "Campaign is still being processed, export will be available once calls are scheduled"
                  : statusStr === "PENDING" || statusStr === "SCHEDULED"
                    ? "No calls have been made yet, export will be available after calls are completed"
                    : "Export is not available for this campaign status";

              return (
                <div key={row.id} className="p-4 space-y-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2 font-semibold text-slate-900 dark:text-slate-100 text-sm">
                      <FileText className="w-4 h-4 text-indigo-600 dark:text-indigo-400 shrink-0" />
                      <span className="truncate">{row.fileName}</span>
                    </div>
                    <StatusBadge status={row.status} />
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-xs text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/40 p-2.5 rounded-lg">
                    <div>
                      <span className="block text-slate-400 dark:text-slate-500">Customers:</span>
                      <span className="font-bold text-emerald-600 dark:text-emerald-300">{row.customerCount}</span>
                    </div>
                    <div>
                      <span className="block text-slate-400 dark:text-slate-500">Scheduled:</span>
                      <span className="text-slate-700 dark:text-slate-200">
                        {formatDateTimeInZone(row.scheduledAt, row.timezone)}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center justify-end gap-2 pt-1">
                    <Tooltip content={exportTooltip}>
                      <span>
                        <button
                          type="button"
                          disabled={!isExportable || isRowDownloading}
                          onClick={() => (!isExportable || isRowDownloading) ? undefined : handleDownloadCsv(row.id, row.fileName)}
                          className={`px-3 py-1.5 text-xs font-semibold text-indigo-700 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-900/40 border border-indigo-300 dark:border-indigo-500/30 rounded-lg inline-flex items-center gap-1 ${
                            !isExportable
                              ? "opacity-50 cursor-not-allowed"
                              : "hover:bg-indigo-100 dark:hover:bg-indigo-800/60"
                          }`}
                        >
                          {isRowDownloading ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Download className="w-3.5 h-3.5" />
                          )}
                          <span>Download CSV</span>
                        </button>
                      </span>
                    </Tooltip>

                    {actions.canView && (
                      <button
                        type="button"
                        onClick={() => onViewDetails(row.id)}
                        className="px-3 py-1.5 text-xs font-semibold text-slate-700 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 rounded-lg"
                      >
                        View
                      </button>
                    )}
                    {actions.canReschedule && (
                      <button
                        type="button"
                        onClick={() => onOpenReschedule(row)}
                        className="px-3 py-1.5 text-xs font-semibold text-indigo-700 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-600/20 rounded-lg"
                      >
                        Reschedule
                      </button>
                    )}
                    {actions.canReupload && (
                      <button
                        type="button"
                        onClick={() => onOpenReupload(row)}
                        className="px-3 py-1.5 text-xs font-semibold text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-600/20 rounded-lg"
                      >
                        Re-upload
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
