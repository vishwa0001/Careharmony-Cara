export type UploadStatus =
  | 'UPLOADED'
  | 'VALIDATING'
  | 'VALIDATION_FAILED'
  | 'SCHEDULED'
  | 'PROCESSING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED';

export interface ValidationError {
  row?: number;
  column?: string;
  message: string;
  type: 'FATAL' | 'WARNING';
}

export interface CustomerRecord {
  empi: string;
  firstName: string;
  lastName: string;
  customerName?: string;
  gender?: string;
  phoneNumber: string;
  practiceName: string;
  practiceCallbackNumber: string;
  rowNumber: number;
}

export interface ValidationSummaryChecklist {
  fileTypeValid: boolean;
  requiredColumnsPresent: boolean;
  recordsFound: boolean;
  phoneNumbersValid: boolean;
  noDuplicatePhones: boolean;
}

export interface ValidationSummary {
  isValid: boolean;
  totalRows: number;
  errorCount: number;
  warningCount: number;
  errors: ValidationError[];
  summaryChecklist: ValidationSummaryChecklist;
}

export interface CampaignDispositionSummary {
  total: number;
  pending: number;
  inProgress: number;
  completed: number;
  callSetupFailed: number;
  dispositions: Record<string, number>;
}

export interface CampaignPatientResult {
  patientId: string;
  empi?: string;
  contactId?: string;
  customerName?: string;
  phoneLast4?: string;
  status: string;
  identityResult?: string;
  disposition?: string;
  attemptCount: number;
  completedAt?: string;
}

export type CallMode = 'NORMAL' | 'DIRECT_HUMAN_HANDOFF';

export interface ScheduledUpload {
  id: string;
  fileName: string;
  fileSize: number;
  customerCount: number;
  scheduledAt: string;
  timezone: string;
  uploadedAt: string;
  status: UploadStatus;
  callMode?: CallMode;
  directAgentEnabled?: boolean;
  humanAgentPhoneNumber?: string;
  validationSummary?: ValidationSummary;
  summary?: CampaignDispositionSummary;
  patientResults?: CampaignPatientResult[];

  originalRecordId?: string;
  rescheduledToId?: string;
  replacedById?: string;
  failureReason?: string;
  cancellationReason?: string;
}

export interface ScheduleSubmissionPayload {
  file: File;
  scheduledAt: string;
  timezone: string;
  customerCount: number;
  validationSummary: ValidationSummary;
  directAgentEnabled?: boolean;
  humanAgentPhoneNumber?: string;
  originalRecordId?: string;
}

export interface StatusActions {
  canView: boolean;
  canCancel: boolean;
  canReschedule: boolean;
  canReupload: boolean;
}
