import type { StatusActions, UploadStatus } from '../types/scheduledCalls.types';

/**
 * Returns available actions based on the scheduled upload status.
 */
export function getAvailableActions(status: UploadStatus): StatusActions {
  switch (status) {
    case 'CANCELLED':
      return { canView: true, canCancel: false, canReschedule: true, canReupload: false };

    case 'FAILED':
    case 'VALIDATION_FAILED':
      return { canView: true, canCancel: false, canReschedule: false, canReupload: true };

    case 'SCHEDULED':
    case 'UPLOADED':
      return { canView: true, canCancel: true, canReschedule: false, canReupload: false };

    case 'VALIDATING':
    case 'PROCESSING':
    case 'COMPLETED':
    default:
      return { canView: true, canCancel: false, canReschedule: false, canReupload: false };
  }
}
