import { useCallback, useEffect, useMemo, useState } from 'react';
import { scheduledCallsService } from '../services/scheduledCalls.service';
import type {
  ScheduleSubmissionPayload,
  ScheduledUpload,
  ValidationError,
  ValidationSummary,
} from '../types/scheduledCalls.types';
import { validateFileMetadata, validateScheduleTime } from '../utils/scheduledCalls.validation';
import { getDefaultTimezone } from '../utils/timezone';
import { CONFIG } from '../config/constants';

export function useScheduledCalls() {
  const [uploads, setUploads] = useState<ScheduledUpload[]>([]);
  const [isLoadingList, setIsLoadingList] = useState<boolean>(true);

  // Form State
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [scheduleTime, setScheduleTime] = useState<string>('');
  const [selectedTimezone, setSelectedTimezone] = useState<string>(getDefaultTimezone());

  // Validation State
  const [metaErrors, setMetaErrors] = useState<ValidationError[]>([]);
  const [metaWarnings, setMetaWarnings] = useState<ValidationError[]>([]);
  const [validationSummary, setValidationSummary] = useState<ValidationSummary | null>(null);
  const [timeError, setTimeError] = useState<string | null>(null);

  // Status & Modal States
  const [isParsing, setIsParsing] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [showConfirmModal, setShowConfirmModal] = useState<boolean>(false);
  const [rescheduleTarget, setRescheduleTarget] = useState<ScheduledUpload | null>(null);
  const [reuploadTarget, setReuploadTarget] = useState<ScheduledUpload | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [activeUploadDetails, setActiveUploadDetails] = useState<ScheduledUpload | null>(null);

  // Filter / Search
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');

  // Load real records from backend API
  const loadUploads = useCallback(async () => {
    try {
      setIsLoadingList(true);
      setErrorMessage(null);
      const list = await scheduledCallsService.getScheduledUploads();
      setUploads(list);
    } catch (err: any) {
      console.error('Failed to load scheduled calls:', err);
      setErrorMessage('Unable to load scheduled calls. Please try again.');
      setUploads([]);
    } finally {
      setIsLoadingList(false);
    }
  }, []);

  useEffect(() => {
    loadUploads();
  }, [loadUploads]);

  // Keep campaign state current while AWS is validating, waiting, or dialing.
  useEffect(() => {
    const hasActiveCampaign = uploads.some((u) =>
      ['UPLOADED', 'VALIDATING', 'SCHEDULED', 'PROCESSING'].includes(u.status)
    );
    if (!hasActiveCampaign) return;
    const timer = window.setInterval(() => {
      void loadUploads();
    }, CONFIG.POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [uploads, loadUploads]);

  // Handle File Selection
  const handleFileSelect = async (file: File | null) => {
    setSuccessMessage(null);
    setErrorMessage(null);
    setValidationSummary(null);
    setMetaErrors([]);
    setMetaWarnings([]);

    if (!file) {
      setSelectedFile(null);
      return;
    }

    const metaCheck = validateFileMetadata(file, uploads);
    if (!metaCheck.isValid) {
      setSelectedFile(null);
      setMetaErrors(metaCheck.errors);
      setMetaWarnings(metaCheck.warnings);
      return;
    }

    setSelectedFile(file);
    setMetaErrors([]);
    setMetaWarnings(metaCheck.warnings);

    try {
      setIsParsing(true);
      const summary = await scheduledCallsService.validateCustomerSheet(file);
      setValidationSummary(summary);
    } catch (err) {
      setErrorMessage('Unable to parse or validate spreadsheet structure.');
    } finally {
      setIsParsing(false);
    }
  };


  // Handle Date/Time Selection
  const handleScheduleTimeChange = (dateTimeIso: string) => {
    setScheduleTime(dateTimeIso);
    setSuccessMessage(null);

    if (!dateTimeIso) {
      setTimeError(null);
      return;
    }

    const check = validateScheduleTime(dateTimeIso, selectedTimezone);
    setTimeError(check.isValid ? null : check.error || 'Invalid schedule time.');
  };

  const isFormValid = useMemo(() => {
    if (!selectedFile) return false;
    if (metaErrors.length > 0) return false;
    if (!validationSummary || !validationSummary.isValid) return false;
    if (!scheduleTime) return false;
    if (!selectedTimezone) return false;
    if (timeError) return false;

    const timeCheck = validateScheduleTime(scheduleTime, selectedTimezone);
    return timeCheck.isValid;
  }, [selectedFile, metaErrors, validationSummary, scheduleTime, selectedTimezone, timeError]);

  const handleInitiateSchedule = () => {
    if (!isFormValid) return;
    setShowConfirmModal(true);
  };

  // Submit New Schedule
  const handleConfirmSchedule = async () => {
    if (!selectedFile || !validationSummary || !scheduleTime) return;

    try {
      setIsSubmitting(true);
      setErrorMessage(null);

      await scheduledCallsService.scheduleCustomerSheet({
        file: selectedFile,
        scheduledAt: scheduleTime,
        timezone: selectedTimezone,
        customerCount: validationSummary.totalRows,
        validationSummary,
      });

      setSuccessMessage('Calls scheduled successfully.');
      setShowConfirmModal(false);
      handleResetForm();
      await loadUploads();
    } catch (err: any) {
      setErrorMessage(err.message || 'Unable to schedule the calls. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Handle Reschedule Cancelled Batch
  const handleConfirmReschedule = async (
    id: string,
    newScheduleTime: string,
    timezone: string
  ) => {
    try {
      setIsSubmitting(true);
      setErrorMessage(null);

      await scheduledCallsService.rescheduleCancelledRecord(id, newScheduleTime, timezone);

      setSuccessMessage('Cancelled batch rescheduled successfully.');
      setRescheduleTarget(null);
      await loadUploads();
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to reschedule batch. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Handle Re-upload Failed Batch
  const handleConfirmReupload = async (
    id: string,
    file: File,
    scheduleTime: string,
    timezone: string,
    customerCount: number,
    validationSummary: ValidationSummary
  ) => {
    try {
      setIsSubmitting(true);
      setErrorMessage(null);

      const payload: ScheduleSubmissionPayload = {
        file,
        scheduledAt: scheduleTime,
        timezone,
        customerCount,
        validationSummary,
      };

      await scheduledCallsService.reuploadFailedRecord(id, payload);

      setSuccessMessage('Replacement calling batch scheduled successfully.');
      setReuploadTarget(null);
      await loadUploads();
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to re-upload replacement batch.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleResetForm = () => {
    setSelectedFile(null);
    setScheduleTime('');
    setMetaErrors([]);
    setMetaWarnings([]);
    setValidationSummary(null);
    setTimeError(null);
    setShowConfirmModal(false);
  };

  const handleViewDetails = async (id: string) => {
    try {
      const details = await scheduledCallsService.getScheduledUploadDetails(id);
      if (details) {
        setActiveUploadDetails(details);
      } else {
        setErrorMessage('Could not find item details.');
      }
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to load item details.');
    }
  };

  const handleCloseDetails = () => {
    setActiveUploadDetails(null);
  };

  const handleCancelSchedule = async (id: string) => {
    try {
      await scheduledCallsService.cancelSchedule(id);
      await loadUploads();
      if (activeUploadDetails && activeUploadDetails.id === id) {
        setActiveUploadDetails((prev) => (prev ? { ...prev, status: 'CANCELLED' } : null));
      }
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to cancel schedule.');
    }
  };

  const filteredUploads = useMemo(() => {
    return uploads.filter((item) => {
      const matchesSearch = item.fileName.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesStatus = statusFilter === 'ALL' || item.status === statusFilter;
      return matchesSearch && matchesStatus;
    });
  }, [uploads, searchQuery, statusFilter]);

  return {
    uploads: filteredUploads,
    rawUploadsList: uploads,
    totalUploadsCount: uploads.length,
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
    refetchUploads: loadUploads,
  };
}
