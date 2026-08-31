import React, { useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, Loader2, UploadCloud, X } from 'lucide-react';
import { CONFIG } from '../../../config/constants';
import type { ValidationError, ValidationSummary } from '../../../types/scheduledCalls.types';
import { downloadSampleCsv } from '../../../utils/sampleCsvGenerator';

interface CustomerSheetUploadProps {
  selectedFile: File | null;
  isParsing: boolean;
  metaErrors: ValidationError[];
  metaWarnings: ValidationError[];
  validationSummary: ValidationSummary | null;
  onFileSelect: (file: File | null) => void;
}

export const CustomerSheetUpload: React.FC<CustomerSheetUploadProps> = ({
  selectedFile,
  isParsing,
  metaErrors,
  metaWarnings,
  validationSummary,
  onFileSelect,
}) => {
  const [isDragOver, setIsDragOver] = useState<boolean>(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      onFileSelect(e.dataTransfer.files[0]);
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      onFileSelect(e.target.files[0]);
    }
    if (e.target) {
      e.target.value = '';
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="text-sm font-semibold text-slate-900 dark:text-slate-200 flex items-center gap-2">
          <FileSpreadsheet className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
          Customer Sheet
        </label>
        <span className="text-xs text-slate-500 dark:text-slate-400">
          Max {CONFIG.MAX_FILE_SIZE_MB}MB (.csv only)
        </span>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".csv,text/csv"
        className="hidden"
        onChange={handleFileInputChange}
      />

      {!selectedFile ? (
        // Dropzone Area
        <div className="space-y-3">
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all duration-200 group ${
              isDragOver
                ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-500/10'
                : 'border-slate-300 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/40 hover:border-slate-400 dark:hover:border-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800/70'
            }`}
          >
            <div className="mx-auto w-10 h-10 rounded-full bg-indigo-100 dark:bg-indigo-500/10 border border-indigo-200 dark:border-indigo-500/20 text-indigo-600 dark:text-indigo-400 flex items-center justify-center mb-2 group-hover:scale-110 transition-transform">
              <UploadCloud className="w-5 h-5" />
            </div>
            <p className="text-xs sm:text-sm font-medium text-slate-800 dark:text-slate-200">
              Drag & drop your CSV customer sheet here
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 mb-3">Supported CSV headers: empi, first_name, last_name, gender, phone_number, practice_name, practice_callback_number, direct agent</p>

            <button
              type="button"
              className="inline-flex items-center px-3.5 py-1.5 text-xs font-semibold text-indigo-700 dark:text-indigo-300 bg-indigo-100 dark:bg-indigo-600/20 hover:bg-indigo-200 dark:hover:bg-indigo-600/30 border border-indigo-300 dark:border-indigo-500/30 rounded-lg transition-colors"
            >
              Choose CSV File
            </button>
          </div>

          {/* Validation Fatal Errors when no file is selected */}
          {metaErrors.map((err, i) => (
            <div
              key={i}
              className="flex items-start gap-2 p-3 rounded-lg bg-rose-50 dark:bg-rose-500/10 border border-rose-200 dark:border-rose-500/30 text-xs text-rose-800 dark:text-rose-300"
            >
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5 text-rose-600 dark:text-rose-400" />
              <div>
                <span className="font-semibold">Error: </span>
                {err.message}
              </div>
            </div>
          ))}

          {/* Sample CSV Template Banner */}
          <div className="bg-indigo-50/70 dark:bg-indigo-950/30 border border-indigo-200 dark:border-indigo-500/20 rounded-xl p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
            <div>
              <p className="text-xs font-semibold text-indigo-900 dark:text-indigo-200">
                Don't have a template?
              </p>
              <p className="text-[11px] text-slate-600 dark:text-slate-400 mt-0.5">
                Download the CSV template to prepare your customer calling list.
              </p>
            </div>

            <button
              type="button"
              onClick={() => downloadSampleCsv()}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-indigo-700 dark:text-indigo-300 hover:text-indigo-900 dark:hover:text-white bg-white dark:bg-indigo-900/40 hover:bg-indigo-100 dark:hover:bg-indigo-800/60 border border-indigo-300 dark:border-indigo-500/30 rounded-lg transition-all shrink-0 self-start sm:self-auto shadow-sm"
            >
              <Download className="w-3.5 h-3.5" />
              Download Sample CSV
            </button>
          </div>
        </div>

      ) : (
        // Selected File Card
        <div className="bg-white dark:bg-slate-800/90 border border-slate-200 dark:border-slate-700 rounded-xl p-4 space-y-3 shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3 min-w-0">
              <div className="p-2.5 bg-emerald-100 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 rounded-lg border border-emerald-200 dark:border-emerald-500/20 shrink-0">
                <CheckCircle2 className="w-5 h-5" />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">
                  {selectedFile.name}
                </p>
                <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                  <span>{formatFileSize(selectedFile.size)}</span>
                  <span>•</span>
                  <span className="uppercase">{selectedFile.name.split('.').pop()}</span>
                  {validationSummary?.isValid && (
                    <>
                      <span>•</span>
                      <span className="text-emerald-600 dark:text-emerald-400 font-semibold">
                        {validationSummary.totalRows} customers
                      </span>
                    </>
                  )}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={isParsing}
                className="px-3 py-1.5 text-xs font-medium text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white bg-slate-100 dark:bg-slate-700/60 hover:bg-slate-200 dark:hover:bg-slate-700 rounded-lg transition-colors disabled:opacity-50"
              >
                Change
              </button>
              <button
                type="button"
                onClick={() => onFileSelect(null)}
                disabled={isParsing}
                className="p-1.5 text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 bg-slate-100 dark:bg-slate-700/60 hover:bg-rose-50 dark:hover:bg-rose-500/20 rounded-lg transition-colors disabled:opacity-50"
                title="Remove file"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Loading Indicator */}
          {isParsing && (
            <div className="flex items-center gap-2 text-xs text-indigo-600 dark:text-indigo-400 pt-2 border-t border-slate-200 dark:border-slate-700/60">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>Validating customer sheet data & phone formats...</span>
            </div>
          )}

          {/* Duplicate Filename Warning Banner */}
          {metaWarnings.map((warn, i) => (
            <div
              key={i}
              className="flex items-start gap-2 p-3 rounded-lg bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/30 text-xs text-amber-800 dark:text-amber-300"
            >
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5 text-amber-600 dark:text-amber-400" />
              <div>
                <span className="font-semibold">Warning: </span>
                {warn.message}
              </div>
            </div>
          ))}

          {/* File Metadata Fatal Errors */}
          {metaErrors.map((err, i) => (
            <div
              key={i}
              className="flex items-start gap-2 p-3 rounded-lg bg-rose-50 dark:bg-rose-500/10 border border-rose-200 dark:border-rose-500/30 text-xs text-rose-800 dark:text-rose-300"
            >
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5 text-rose-600 dark:text-rose-400" />
              <div>
                <span className="font-semibold">Error: </span>
                {err.message}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
