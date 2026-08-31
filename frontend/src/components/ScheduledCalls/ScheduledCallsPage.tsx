import React, { useRef } from 'react';
import { CalendarClock, CheckCircle2, Headset, Loader2, Phone, RotateCcw, Send } from 'lucide-react';
import { useScheduledCalls } from '../../hooks/useScheduledCalls';
import { CustomerSheetUpload } from './components/CustomerSheetUpload';
import { Header } from './components/Header';
import { RescheduleModal } from './components/RescheduleModal';
import { ReuploadModal } from './components/ReuploadModal';
import { ScheduleConfirmationModal } from './components/ScheduleConfirmationModal';
import { ScheduledUploadDetailsDrawer } from './components/ScheduledUploadDetailsDrawer';
import { ScheduledUploadsTable } from './components/ScheduledUploadsTable';
import { ScheduleDateTimePicker } from './components/ScheduleDateTimePicker';
import { ValidationSummaryCallout } from './components/ValidationSummaryCallout';

export const ScheduledCallsPage: React.FC = () => {
  const formCardRef = useRef<HTMLDivElement>(null);
  const {
    uploads,
    totalUploadsCount,
    isLoadingList,
    selectedFile,
    scheduleTime,
    selectedTimezone,
    setSelectedTimezone,
    metaErrors,
    metaWarnings,
    validationSummary,
    timeError,
    isParsing,
    isSubmitting,
    isFormValid,
    showConfirmModal,
    rescheduleTarget,
    reuploadTarget,
    setRescheduleTarget,
    setReuploadTarget,
    successMessage,
    errorMessage,
    activeUploadDetails,
    searchQuery,
    statusFilter,
    setSearchQuery,
    setStatusFilter,
    directAgentEnabled,
    humanAgentPhoneNumber,
    agentPhoneError,
    handleHumanAgentPhoneChange,
    handleToggleDirectAgent,
    handleFileSelect,
    handleScheduleTimeChange,
    handleInitiateSchedule,
    handleConfirmSchedule,
    handleConfirmReschedule,
    handleConfirmReupload,
    handleResetForm,
    handleViewDetails,
    handleCloseDetails,
    handleCancelSchedule,
    setShowConfirmModal,
  } = useScheduledCalls();

  const scrollToForm = () => {
    formCardRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const scheduledActiveCount = uploads.filter((u) => u.status === 'SCHEDULED').length;

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 flex flex-col font-sans selection:bg-indigo-500 selection:text-white transition-colors duration-200">
      {/* App Header */}
      <Header scheduledCount={scheduledActiveCount} />

      {/* Main Content Area */}
      <main className="max-w-7xl mx-auto px-4 sm:px-8 pb-16 space-y-10 flex-1 w-full">
        {/* Global Feedback Banners */}
        {successMessage && (
          <div className="flex items-center gap-3 p-4 rounded-xl bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/30 text-emerald-800 dark:text-emerald-300 text-sm animate-in fade-in shadow-sm">
            <CheckCircle2 className="w-5 h-5 text-emerald-600 dark:text-emerald-400 shrink-0" />
            <span className="font-semibold">{successMessage}</span>
          </div>
        )}

        {errorMessage && (
          <div className="flex items-center gap-3 p-4 rounded-xl bg-rose-50 dark:bg-rose-500/10 border border-rose-200 dark:border-rose-500/30 text-rose-800 dark:text-rose-300 text-sm animate-in fade-in shadow-sm">
            <span className="font-semibold">{errorMessage}</span>
          </div>
        )}

        {/* SECTION A — Schedule New Calls */}
        <section ref={formCardRef} className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="p-2 rounded-lg bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border border-indigo-200 dark:border-indigo-500/20">
                <CalendarClock className="w-5 h-5" />
              </div>
              <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">Schedule New Calls</h2>
            </div>
            {selectedFile && (
              <button
                type="button"
                onClick={handleResetForm}
                disabled={isSubmitting}
                className="text-xs text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 flex items-center gap-1 transition-colors"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                Reset Form
              </button>
            )}
          </div>

          <div className="bg-white dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800/80 rounded-2xl p-6 sm:p-8 shadow-sm dark:shadow-2xl space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 sm:gap-8">
              {/* File Upload Column */}
              <CustomerSheetUpload
                selectedFile={selectedFile}
                isParsing={isParsing}
                metaErrors={metaErrors}
                metaWarnings={metaWarnings}
                validationSummary={validationSummary}
                onFileSelect={handleFileSelect}
              />

              {/* Date & Time & Timezone Picker Column */}
              <ScheduleDateTimePicker
                scheduleTime={scheduleTime}
                selectedTimezone={selectedTimezone}
                timeError={timeError}
                onScheduleTimeChange={handleScheduleTimeChange}
                onTimezoneChange={setSelectedTimezone}
              />
            </div>

            {/* SECTION: Direct to Human Agent (Campaign-Level Setting) */}
            <div className="bg-slate-50/70 dark:bg-slate-800/40 border border-slate-200 dark:border-slate-800 rounded-xl p-4 sm:p-5 space-y-4">
              <div className="flex items-start justify-between gap-4">
                <div className="space-y-1">
                  <label htmlFor="direct-agent-toggle" className="text-sm font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2 cursor-pointer">
                    <Headset className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                    Direct to Human Agent
                  </label>
                  <p className="text-xs text-slate-500 dark:text-slate-400 max-w-xl">
                    When enabled, confirmed customers in this campaign will be connected directly to a human specialist upon identity confirmation without automated screening.
                  </p>
                </div>

                <div className="flex items-center pt-0.5">
                  <button
                    id="direct-agent-toggle"
                    type="button"
                    role="switch"
                    aria-checked={directAgentEnabled}
                    onClick={() => handleToggleDirectAgent(!directAgentEnabled)}
                    className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-indigo-600 focus:ring-offset-2 dark:focus:ring-offset-slate-900 ${
                      directAgentEnabled ? 'bg-indigo-600' : 'bg-slate-300 dark:bg-slate-700'
                    }`}
                  >
                    <span
                      aria-hidden="true"
                      className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-lg ring-0 transition duration-200 ease-in-out ${
                        directAgentEnabled ? 'translate-x-5' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>
              </div>

              {/* Human Agent Phone Number Input (Always visible and required) */}
              <div className="pt-3 border-t border-slate-200 dark:border-slate-700/60 space-y-2">
                <label htmlFor="human-agent-phone" className="block text-xs font-semibold text-slate-800 dark:text-slate-200">
                  Human Agent Phone Number <span className="text-rose-500">*</span>
                </label>
                <div className="relative max-w-md">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                    <Phone className="w-4 h-4" />
                  </div>
                  <input
                    id="human-agent-phone"
                    type="tel"
                    value={humanAgentPhoneNumber}
                    onChange={(e) => handleHumanAgentPhoneChange(e.target.value)}
                    placeholder="+1 (443) 726-4019"
                    className={`w-full pl-9 pr-4 py-2 text-xs sm:text-sm bg-white dark:bg-slate-900 border rounded-xl shadow-sm focus:outline-none focus:ring-2 transition-all ${
                      agentPhoneError
                        ? 'border-rose-300 dark:border-rose-700 focus:ring-rose-500 text-rose-900 dark:text-rose-200'
                        : 'border-slate-300 dark:border-slate-700 focus:ring-indigo-500 dark:focus:ring-indigo-400 text-slate-900 dark:text-slate-100'
                    }`}
                  />
                </div>
                {agentPhoneError ? (
                  <p className="text-xs text-rose-600 dark:text-rose-400 font-medium">
                    {agentPhoneError}
                  </p>
                ) : (
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">
                    Enter the human specialist phone number (e.g. +14437264019). Used for direct handoff when toggle is ON, or mid-call escalation when caller agrees to transfer in Normal Cara Flow.
                  </p>
                )}
              </div>
            </div>

            {/* Validation Breakdown Summary */}
            <ValidationSummaryCallout summary={validationSummary} />

            {/* Primary Action Row */}
            <div className="pt-4 border-t border-slate-200 dark:border-slate-800/60 flex items-center justify-between gap-4 flex-wrap">
              <div className="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-2">
                {selectedFile && validationSummary?.isValid && (
                  <span className="text-emerald-600 dark:text-emerald-400 font-semibold flex items-center gap-1">
                    <CheckCircle2 className="w-4 h-4" />
                    Sheet Validated ({validationSummary.totalRows} customers)
                  </span>
                )}
              </div>

              <div className="flex items-center gap-3 ml-auto">
                {selectedFile && (
                  <button
                    type="button"
                    onClick={handleResetForm}
                    disabled={isSubmitting}
                    className="px-4 py-2.5 text-xs font-semibold text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700/60 border border-slate-200 dark:border-slate-700/60 rounded-xl transition-colors disabled:opacity-50"
                  >
                    Cancel
                  </button>
                )}

                <button
                  type="button"
                  onClick={handleInitiateSchedule}
                  disabled={!isFormValid || isSubmitting}
                  className="px-6 py-3 text-xs font-bold text-white bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-200 dark:disabled:bg-slate-800 disabled:text-slate-400 dark:disabled:text-slate-500 border border-indigo-500/30 rounded-xl shadow-lg shadow-indigo-600/25 flex items-center gap-2 transition-all disabled:opacity-50 disabled:shadow-none cursor-pointer disabled:cursor-not-allowed"
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Scheduling...
                    </>
                  ) : (
                    <>
                      <Send className="w-4 h-4" />
                      Schedule Calls
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* SECTION B — Scheduled Uploads Table */}
        <section className="pt-6">
          <ScheduledUploadsTable
            uploads={uploads}
            totalCount={totalUploadsCount}
            isLoading={isLoadingList}
            searchQuery={searchQuery}
            statusFilter={statusFilter}
            onSearchChange={setSearchQuery}
            onFilterChange={setStatusFilter}
            onViewDetails={handleViewDetails}
            onOpenReschedule={setRescheduleTarget}
            onOpenReupload={setReuploadTarget}
            onCancelSchedule={handleCancelSchedule}
            onEmptyAction={scrollToForm}
          />
        </section>
      </main>

      {/* Schedule Confirmation Modal */}
      <ScheduleConfirmationModal
        isOpen={showConfirmModal}
        fileName={selectedFile?.name || ''}
        customerCount={validationSummary?.totalRows || 0}
        scheduleTime={scheduleTime}
        timezone={selectedTimezone}
        directAgentEnabled={directAgentEnabled}
        humanAgentPhoneNumber={humanAgentPhoneNumber}
        isSubmitting={isSubmitting}
        onClose={() => setShowConfirmModal(false)}
        onConfirm={handleConfirmSchedule}
      />

      {/* Reschedule Modal */}
      <RescheduleModal
        isOpen={Boolean(rescheduleTarget)}
        targetRecord={rescheduleTarget}
        isSubmitting={isSubmitting}
        onClose={() => setRescheduleTarget(null)}
        onConfirmReschedule={handleConfirmReschedule}
      />

      {/* Re-upload Modal */}
      <ReuploadModal
        isOpen={Boolean(reuploadTarget)}
        targetRecord={reuploadTarget}
        isSubmitting={isSubmitting}
        onClose={() => setReuploadTarget(null)}
        onConfirmReupload={handleConfirmReupload}
      />

      {/* Details Slide-Over Drawer */}
      <ScheduledUploadDetailsDrawer
        upload={activeUploadDetails}
        onClose={handleCloseDetails}
        onCancelSchedule={handleCancelSchedule}
        onOpenReschedule={setRescheduleTarget}
        onOpenReupload={setReuploadTarget}
      />
    </div>
  );
};
