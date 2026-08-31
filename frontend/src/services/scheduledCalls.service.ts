import { CONFIG } from '../config/constants';
import type {
  ScheduleSubmissionPayload,
  ScheduledUpload,
  ValidationSummary,
} from '../types/scheduledCalls.types';
import { parseCustomerSheet } from '../utils/fileParser';
import { validateCsvFile, validateSheetContent } from '../utils/scheduledCalls.validation';

const isTestEnv = (typeof process !== 'undefined' && process.env?.NODE_ENV === 'test') || import.meta.env?.MODE === 'test';


// Initial mock dataset for offline unit testing environment only
const INITIAL_MOCK_UPLOADS: ScheduledUpload[] = [
  {
    id: 'sch-101',
    fileName: 'customers_aug18.xlsx',
    fileSize: 253952,
    customerCount: 248,
    scheduledAt: new Date(Date.now() + 12 * 3600 * 1000).toISOString(),
    timezone: 'Asia/Kolkata',
    uploadedAt: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
    status: 'SCHEDULED',
    validationSummary: {
      isValid: true,
      totalRows: 248,
      errorCount: 0,
      warningCount: 0,
      errors: [],
      summaryChecklist: {
        fileTypeValid: true,
        requiredColumnsPresent: true,
        recordsFound: true,
        phoneNumbersValid: true,
        noDuplicatePhones: true,
      },
    },
  },
  {
    id: 'sch-102',
    fileName: 'customers_aug19.csv',
    fileSize: 122880,
    customerCount: 120,
    scheduledAt: new Date(Date.now() + 36 * 3600 * 1000).toISOString(),
    timezone: 'America/New_York',
    uploadedAt: new Date(Date.now() - 5 * 3600 * 1000).toISOString(),
    status: 'SCHEDULED',
    validationSummary: {
      isValid: true,
      totalRows: 120,
      errorCount: 0,
      warningCount: 0,
      errors: [],
      summaryChecklist: {
        fileTypeValid: true,
        requiredColumnsPresent: true,
        recordsFound: true,
        phoneNumbersValid: true,
        noDuplicatePhones: true,
      },
    },
  },
  {
    id: 'sch-103',
    fileName: 'cancelled_calling_batch.xlsx',
    fileSize: 94208,
    customerCount: 95,
    scheduledAt: new Date(Date.now() + 24 * 3600 * 1000).toISOString(),
    timezone: 'Asia/Kolkata',
    uploadedAt: new Date(Date.now() - 10 * 3600 * 1000).toISOString(),
    status: 'CANCELLED',
    cancellationReason: 'Cancelled by operator before launch',
  },
  {
    id: 'sch-104',
    fileName: 'failed_leads_list.csv',
    fileSize: 45056,
    customerCount: 45,
    scheduledAt: new Date(Date.now() - 6 * 3600 * 1000).toISOString(),
    timezone: 'Europe/London',
    uploadedAt: new Date(Date.now() - 8 * 3600 * 1000).toISOString(),
    status: 'FAILED',
    failureReason: 'Upstream telephony service connection timeout during batch initialization.',
  },
  {
    id: 'sch-105',
    fileName: 'corrupted_lead_list.csv',
    fileSize: 15360,
    customerCount: 15,
    scheduledAt: new Date(Date.now() - 12 * 3600 * 1000).toISOString(),
    timezone: 'Asia/Kolkata',
    uploadedAt: new Date(Date.now() - 14 * 3600 * 1000).toISOString(),
    status: 'VALIDATION_FAILED',
    validationSummary: {
      isValid: false,
      totalRows: 15,
      errorCount: 3,
      warningCount: 0,
      errors: [
        { row: 7, column: 'phoneNumber', message: 'Row 7: Phone number is missing.', type: 'FATAL' },
        { row: 12, column: 'phoneNumber', message: 'Row 12: Invalid phone number (9999).', type: 'FATAL' },
        { row: 15, column: 'customerName', message: 'Row 15: Customer name is missing.', type: 'FATAL' },
      ],
      summaryChecklist: {
        fileTypeValid: true,
        requiredColumnsPresent: true,
        recordsFound: true,
        phoneNumbersValid: false,
        noDuplicatePhones: true,
      },
    },
  },
];

export function mapApiRecordToScheduledUpload(raw: any): ScheduledUpload {
  const rawStatus = String(raw.status || 'PENDING').toUpperCase();

  let uiStatus: ScheduledUpload['status'] = 'SCHEDULED';
  if (rawStatus === 'UPLOAD_PENDING' || rawStatus === 'UPLOADED') {
    uiStatus = 'UPLOADED';
  } else if (rawStatus === 'VALIDATING') {
    uiStatus = 'VALIDATING';
  } else if (rawStatus === 'READY' || rawStatus === 'SCHEDULED' || rawStatus === 'PENDING') {
    uiStatus = 'SCHEDULED';
  } else if (rawStatus === 'RUNNING' || rawStatus === 'PROCESSING') {
    uiStatus = 'PROCESSING';
  } else if (rawStatus === 'VALIDATION_FAILED') {
    uiStatus = 'VALIDATION_FAILED';
  } else if (['INGESTION_FAILED', 'UPLOAD_FAILED', 'FAILED'].includes(rawStatus)) {
    uiStatus = 'FAILED';
  } else if (rawStatus === 'CANCELLED') {
    uiStatus = 'CANCELLED';
  } else if (rawStatus === 'COMPLETED') {
    uiStatus = 'COMPLETED';
  }

  const totalRows = Number(raw.patientCount ?? raw.totalRows ?? raw.customerCount ?? 0);
  const invalidRows = Number(raw.invalidRows ?? 0);
  const validRows = Number(raw.validRows ?? Math.max(0, totalRows - invalidRows));

  const validationSummary: ValidationSummary = {
    isValid: !['VALIDATION_FAILED', 'FAILED'].includes(uiStatus),
    totalRows,
    errorCount: invalidRows,
    warningCount: 0,
    errors: raw.failureReason ? [{ message: raw.failureReason, type: 'FATAL' }] : [],
    summaryChecklist: {
      fileTypeValid: true,
      requiredColumnsPresent: true,
      recordsFound: totalRows > 0,
      phoneNumbersValid: invalidRows === 0,
      noDuplicatePhones: true,
    },
  };

  return {
    id: raw.campaignId || raw.batchId || raw.id || `sch-${Date.now()}`,
    fileName: raw.fileName || 'patients.csv',
    fileSize: Number(raw.fileSize || 0),
    customerCount: validRows > 0 ? validRows : totalRows,
    scheduledAt: raw.scheduledAt || raw.scheduledFor || new Date().toISOString(),
    timezone: raw.timezone || CONFIG.TIMEZONE.IANA,
    uploadedAt: raw.uploadedAt || raw.createdAt || new Date().toISOString(),
    status: uiStatus,
    callMode: raw.callMode || 'NORMAL',
    humanAgentPhoneNumber: raw.humanAgentPhoneNumber,
    validationSummary,
    summary: raw.summary,
    patientResults: raw.patientResults,
    originalRecordId: raw.originalRecordId,
    rescheduledToId: raw.rescheduledToId,
    replacedById: raw.replacedById,
    failureReason: raw.failureReason,
    cancellationReason: raw.cancellationReason,
  };
}

function runtimeBearerToken(): string {
  const fromEnv = (import.meta as any).env?.VITE_CAMPAIGN_API_BEARER_TOKEN || '';
  if (fromEnv) return fromEnv;
  if (typeof window !== 'undefined') {
    return window.sessionStorage?.getItem('caraCampaignApiToken') || '';
  }
  return '';
}

class ScheduledCallsService {
  private mockUploads: ScheduledUpload[] = [...INITIAL_MOCK_UPLOADS];
  private apiBaseUrl: string = (CONFIG.API?.BASE_URL || '').replace(/\/$/, '');
  private legacyUploadApiEndpoint: string = CONFIG.API?.LEGACY_UPLOAD_URL || '';
  private legacyListApiEndpoint: string = CONFIG.API?.LEGACY_LIST_URL || '';

  private async apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
    if (!this.apiBaseUrl) throw new Error('VITE_CAMPAIGN_API_BASE_URL is not configured.');
    const token = runtimeBearerToken();
    const headers = new Headers(init.headers || {});
    headers.set('Accept', 'application/json');
    if (token) headers.set('Authorization', `Bearer ${token}`);
    return fetch(`${this.apiBaseUrl}${path}`, { ...init, headers });
  }

  async getScheduledUploads(): Promise<ScheduledUpload[]> {
    if (this.apiBaseUrl && !isTestEnv) {
      const resp = await this.apiFetch('/campaigns');
      if (!resp.ok) throw new Error(`Failed to fetch campaigns: HTTP ${resp.status}`);
      const data = await resp.json();
      return (data.items || []).map((item: any) => mapApiRecordToScheduledUpload(item));
    }

    if (this.legacyListApiEndpoint && !isTestEnv) {
      const resp = await fetch(this.legacyListApiEndpoint, { headers: { Accept: 'application/json' } });
      if (!resp.ok) throw new Error(`Failed to fetch scheduled calls from API: HTTP ${resp.status}`);
      const data = await resp.json();
      return (data.items || (Array.isArray(data) ? data : [])).map((item: any) => mapApiRecordToScheduledUpload(item));
    }
    return [...this.mockUploads];
  }

  async getScheduledUploadDetails(id: string): Promise<ScheduledUpload | null> {
    if (this.apiBaseUrl && !isTestEnv) {
      const resp = await this.apiFetch(`/campaigns/${encodeURIComponent(id)}`);
      if (resp.status === 404) return null;
      if (!resp.ok) throw new Error(`Failed to fetch campaign detail: HTTP ${resp.status}`);
      const upload = mapApiRecordToScheduledUpload(await resp.json());
      try {
        const patientsResp = await this.apiFetch(`/campaigns/${encodeURIComponent(id)}/patients`);
        if (patientsResp.ok) {
          const data = await patientsResp.json();
          upload.patientResults = data.items || [];
          upload.summary = data.summary || upload.summary;
        }
      } catch {
        // Campaign details remain useful even if patient-level results are unavailable.
      }
      return upload;
    }

    if (this.legacyListApiEndpoint && !isTestEnv) {
      const url = `${this.legacyListApiEndpoint}?batchId=${encodeURIComponent(id)}`;
      const resp = await fetch(url, { headers: { Accept: 'application/json' } });
      if (resp.status === 404) return null;
      if (!resp.ok) throw new Error(`Failed to fetch batch detail: HTTP ${resp.status}`);
      return mapApiRecordToScheduledUpload(await resp.json());
    }

    const item = this.mockUploads.find((u) => u.id === id);
    return item ? { ...item } : null;
  }

  async validateCustomerSheet(file: File): Promise<ValidationSummary> {
    const parsedData = await parseCustomerSheet(file);
    return validateSheetContent(parsedData);
  }

  async scheduleCustomerSheet(payload: ScheduleSubmissionPayload): Promise<ScheduledUpload> {
    const csvCheck = validateCsvFile(payload.file);
    if (!csvCheck.valid) {
      throw new Error(csvCheck.error || 'Only CSV files are supported. Please upload a .csv file.');
    }

    if (this.apiBaseUrl && !isTestEnv) {
      const initResp = await this.apiFetch('/uploads', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fileName: payload.file.name,
          fileSize: payload.file.size,
          scheduledAt: payload.scheduledAt,
          timezone: payload.timezone || CONFIG.TIMEZONE.IANA,
          customerCount: payload.customerCount,
          originalRecordId: payload.originalRecordId,
        }),
      });
      if (!initResp.ok) {
        const errBody = await initResp.json().catch(() => ({}));
        throw new Error(errBody.error || `Failed to initialize upload: HTTP ${initResp.status}`);
      }

      const initData = await initResp.json();
      console.log('Upload API response:', initData);

      const uploadUrl = initData.uploadUrl || initData.upload_url || initData.presignedUrl;
      const uploadHeaders = initData.uploadHeaders || initData.headers;
      const batchId = initData.batchId || initData.batch_id;
      const campaignId = initData.campaignId || initData.campaign_id;

      if (!uploadUrl) {
        throw new Error('Upload initialization failed: missing uploadUrl in response.');
      }

      const uploadResp = await fetch(uploadUrl, {
        method: 'PUT',
        headers: uploadHeaders || { 'Content-Type': 'text/csv' },
        body: payload.file,
      });
      if (!uploadResp.ok) throw new Error(`S3 direct upload failed with status ${uploadResp.status}`);
      return {
        id: campaignId || batchId || `upload-${Date.now()}`,
        fileName: payload.file.name,
        fileSize: payload.file.size,
        customerCount: payload.customerCount,
        scheduledAt: payload.scheduledAt,
        timezone: payload.timezone || CONFIG.TIMEZONE.IANA,
        uploadedAt: new Date().toISOString(),
        status: 'UPLOADED',
        validationSummary: payload.validationSummary,
        originalRecordId: payload.originalRecordId,
      };
    }

    if (this.legacyUploadApiEndpoint && !isTestEnv) {
      const initResp = await fetch(this.legacyUploadApiEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fileName: payload.file.name,
          scheduledAt: payload.scheduledAt,
          timezone: payload.timezone || CONFIG.TIMEZONE.IANA,
          customerCount: payload.customerCount,
          originalRecordId: payload.originalRecordId,
        }),
      });
      if (!initResp.ok) throw new Error(`Failed to initialize upload: HTTP ${initResp.status}`);
      const { batchId, uploadUrl } = await initResp.json();
      const uploadResp = await fetch(uploadUrl, { method: 'PUT', headers: { 'Content-Type': 'text/csv' }, body: payload.file });
      if (!uploadResp.ok) throw new Error(`S3 direct upload failed with status ${uploadResp.status}`);
      return {
        id: batchId,
        fileName: payload.file.name,
        fileSize: payload.file.size,
        customerCount: payload.customerCount,
        scheduledAt: payload.scheduledAt,
        timezone: payload.timezone || CONFIG.TIMEZONE.IANA,
        uploadedAt: new Date().toISOString(),
        status: 'UPLOADED',
        validationSummary: payload.validationSummary,
        originalRecordId: payload.originalRecordId,
      };
    }

    const newRecord: ScheduledUpload = {
      id: `sch-${Date.now().toString(36)}`,
      fileName: payload.file.name,
      fileSize: payload.file.size,
      customerCount: payload.customerCount,
      scheduledAt: payload.scheduledAt,
      timezone: payload.timezone || CONFIG.TIMEZONE.IANA,
      uploadedAt: new Date().toISOString(),
      status: 'SCHEDULED',
      validationSummary: payload.validationSummary,
      originalRecordId: payload.originalRecordId,
    };
    this.mockUploads.unshift(newRecord);
    return newRecord;
  }

  async rescheduleCancelledRecord(id: string, newScheduleTime: string, timezone: string): Promise<ScheduledUpload> {
    if (this.apiBaseUrl && !isTestEnv) {
      const resp = await this.apiFetch(`/campaigns/${encodeURIComponent(id)}/reschedule`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scheduledAt: newScheduleTime, timezone }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.error || `Failed to reschedule campaign: HTTP ${resp.status}`);
      }
      const { campaignId, batchId } = await resp.json();
      const created = await this.getScheduledUploadDetails(campaignId || batchId);
      if (!created) throw new Error('Rescheduled campaign was created but could not be loaded.');
      return created;
    }

    if (this.legacyListApiEndpoint && !isTestEnv) {
      throw new Error('Rescheduling requires the unified Cara campaign API.');
    }

    const original = this.mockUploads.find((u) => u.id === id);
    if (!original || original.status !== 'CANCELLED') throw new Error('Only CANCELLED records can be rescheduled.');
    const newRecordId = `sch-${Date.now().toString(36)}`;
    const newRecord: ScheduledUpload = {
      ...original,
      id: newRecordId,
      scheduledAt: newScheduleTime,
      timezone,
      uploadedAt: new Date().toISOString(),
      status: 'SCHEDULED',
      originalRecordId: original.id,
      rescheduledToId: undefined,
      cancellationReason: undefined,
    };
    original.rescheduledToId = newRecordId;
    this.mockUploads.unshift(newRecord);
    return newRecord;
  }

  async reuploadFailedRecord(id: string, payload: ScheduleSubmissionPayload): Promise<ScheduledUpload> {
    if ((!this.apiBaseUrl && !this.legacyUploadApiEndpoint) || isTestEnv) {
      const original = this.mockUploads.find((u) => u.id === id);
      if (!original || (original.status !== 'FAILED' && original.status !== 'VALIDATION_FAILED')) {
        throw new Error('Only FAILED or VALIDATION_FAILED records can be re-uploaded.');
      }
      const newRecord = await this.scheduleCustomerSheet({ ...payload, originalRecordId: original.id });
      original.replacedById = newRecord.id;
      return newRecord;
    }
    return this.scheduleCustomerSheet({ ...payload, originalRecordId: id });
  }

  async cancelSchedule(id: string, reason?: string): Promise<void> {
    if (this.apiBaseUrl && !isTestEnv) {
      const resp = await this.apiFetch(`/campaigns/${encodeURIComponent(id)}/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: reason || 'Cancelled by operator' }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.error || `Failed to cancel campaign: HTTP ${resp.status}`);
      }
      return;
    }
    if (this.legacyListApiEndpoint && !isTestEnv) {
      throw new Error('Cancellation requires the unified Cara campaign API.');
    }
    const item = this.mockUploads.find((u) => u.id === id);
    if (item && (item.status === 'SCHEDULED' || item.status === 'UPLOADED')) {
      item.status = 'CANCELLED';
      item.cancellationReason = reason || 'Cancelled by operator';
    }
  }

  async downloadCampaignCsv(campaignId: string, campaignFileName?: string): Promise<void> {
    let fallbackFilename = `${campaignId}_export.csv`;
    if (campaignFileName) {
      const idx = campaignFileName.lastIndexOf('.');
      const baseName = idx > 0 ? campaignFileName.substring(0, idx) : campaignFileName;
      fallbackFilename = `${baseName}_export.csv`;
    }

    if (this.apiBaseUrl && !isTestEnv) {
      const resp = await this.apiFetch(`/campaigns/${encodeURIComponent(campaignId)}/export`);
      if (!resp.ok) {
        const errBody = await resp.json().catch(() => ({}));
        throw new Error(errBody.error || `Failed to download campaign CSV: HTTP ${resp.status}`);
      }
      const blob = await resp.blob();
      const contentDisposition = resp.headers.get('Content-Disposition');
      let filename = fallbackFilename;
      if (contentDisposition) {
        const match = contentDisposition.match(/filename="?([^"]+)"?/);
        if (match && match[1]) filename = match[1];
      }
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      return;
    }

    const csvContent = [
      'empi,call_id,call_start_datetime,call_end_datetime,disposition,call_summary,requested_callback_date_time,outbound_call_phone_number',
      `TEST001,call_001,2026-08-29T15:00:00Z,2026-08-29T15:05:30Z,COMPLETED,"Mock campaign export data",n/a,+1877523XXXX`,
    ].join('\n');

    if (typeof window !== 'undefined' && typeof document !== 'undefined') {
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = fallbackFilename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    }
  }

  async downloadPatientCallCsv(campaignId: string, _patientId?: string, _callId?: string): Promise<void> {
    return this.downloadCampaignCsv(campaignId);
  }
}

export const scheduledCallsService = new ScheduledCallsService();