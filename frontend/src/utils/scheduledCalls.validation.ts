import { CONFIG } from '../config/constants';
import type {
  ScheduledUpload,
  ValidationError,
  ValidationSummary,
} from '../types/scheduledCalls.types';
import type { ParsedSheetData } from './fileParser';
import { localDateTimeInZoneToUtc } from './timezone';

export interface FileValidationResult {
  valid: boolean;
  error?: string;
}

/**
 * Robust programmatic validation for CSV-only files.
 */
export function validateCsvFile(file: File | null): FileValidationResult {
  if (!file) {
    return { valid: false, error: 'Please select a customer sheet.' };
  }

  const name = file.name || '';
  const lowerName = name.toLowerCase();

  // Must end with .csv
  if (!lowerName.endsWith('.csv')) {
    return {
      valid: false,
      error: 'Only CSV files are supported. Please upload a .csv file.',
    };
  }

  // Reject compound extensions like patients.csv.xlsx or patients.csv.txt
  const parts = lowerName.split('.');
  if (parts.length > 2) {
    const lastExt = parts[parts.length - 1];
    if (lastExt !== 'csv') {
      return {
        valid: false,
        error: 'Only CSV files are supported. Please upload a .csv file.',
      };
    }
  }

  return { valid: true };
}

/**
 * Validates basic file metadata before spreadsheet parsing.
 */
export function validateFileMetadata(
  file: File | null,
  existingUploads: ScheduledUpload[] = []
): { isValid: boolean; errors: ValidationError[]; warnings: ValidationError[] } {
  const errors: ValidationError[] = [];
  const warnings: ValidationError[] = [];

  if (!file) {
    errors.push({
      message: 'Please select a customer sheet.',
      type: 'FATAL',
    });
    return { isValid: false, errors, warnings };
  }

  // 1. Extension check
  const csvCheck = validateCsvFile(file);
  if (!csvCheck.valid) {
    errors.push({
      message: csvCheck.error || 'Only CSV files are supported. Please upload a .csv file.',
      type: 'FATAL',
    });
  }


  // 2. File size check
  if (file.size > CONFIG.MAX_FILE_SIZE_BYTES) {
    errors.push({
      message: `File size exceeds the maximum allowed limit of ${CONFIG.MAX_FILE_SIZE_MB} MB.`,
      type: 'FATAL',
    });
  }

  // 3. Zero-byte check
  if (file.size === 0) {
    errors.push({
      message: 'Selected file is empty.',
      type: 'FATAL',
    });
  }

  // 4. Duplicate filename warning (Non-fatal)
  const isDuplicateName = existingUploads.some(
    (u) => u.fileName.toLowerCase() === file.name.toLowerCase()
  );
  if (isDuplicateName) {
    warnings.push({
      message: `A file with name "${file.name}" has already been uploaded. Please confirm that this is a new customer batch.`,
      type: 'WARNING',
    });
  }

  return {
    isValid: errors.length === 0,
    errors,
    warnings,
  };
}

/**
 * Normalizes phone numbers to standard format (removes spaces, dashes, parentheses).
 */
export function sanitizePhoneNumber(phone: string): string {
  return phone.replace(/[\s\-\(\)]/g, '');
}

/**
 * Validates E.164 or international/10-digit phone format.
 */
export function isValidPhoneNumber(phone: string): boolean {
  const cleaned = sanitizePhoneNumber(phone);
  // Valid if 10 to 15 digits, optionally prefixed with '+'
  const phoneRegex = /^\+?[1-9]\d{9,14}$/;
  return phoneRegex.test(cleaned);
}

export const REQUIRED_CARA_HEADERS = [
  'empi',
  'first_name',
  'last_name',
  'gender',
  'phone_number',
  'practice_name',
  'practice_callback_number',
] as const;

/**
 * Helper to match expected column headers flexibly (handling BOM, whitespace, case, underscores).
 */
function findMatchingHeader(
  headers: string[],
  target: string
): string | undefined {
  const cleanTarget = target.replace(/^\ufeff/, '').toLowerCase().trim().replace(/[^a-z0-9]/g, '');
  return headers.find((h) => {
    const cleanH = h.replace(/^\ufeff/, '').toLowerCase().trim().replace(/[^a-z0-9]/g, '');
    return cleanH === cleanTarget;
  });
}

/**
 * Validates spreadsheet structure and individual customer record rows.
 */
export function validateSheetContent(
  parsedData: ParsedSheetData
): ValidationSummary {
  const { headers, rows, rawRowCount } = parsedData;
  const errors: ValidationError[] = [];
  let errorCount = 0;

  const requiredHeaders = [...REQUIRED_CARA_HEADERS];

  const missingHeaders: string[] = [];
  const foundHeaders: Record<string, string | undefined> = {};

  requiredHeaders.forEach((req) => {
    const matched = findMatchingHeader(headers, req);
    foundHeaders[req] = matched;
    if (!matched) {
      missingHeaders.push(req);
    }
  });

  const directAgentHeader = findMatchingHeader(headers, 'direct_agent') || findMatchingHeader(headers, 'direct agent');

  const requiredColumnsPresent = missingHeaders.length === 0;
  if (!requiredColumnsPresent) {
    errors.push({
      message: `Invalid CSV format. Missing required column: ${missingHeaders.join(', ')}`,
      type: 'FATAL',
    });
    errorCount++;
  }

  // Check records count
  const recordsFound = rawRowCount > 0;
  if (rawRowCount === 0) {
    errors.push({
      message: 'File contains no customer rows.',
      type: 'FATAL',
    });
    errorCount++;
  }

  let phoneNumbersValid = true;
  let noDuplicatePhones = true;
  const seenPhones = new Set<string>();

  if (requiredColumnsPresent && recordsFound) {
    rows.forEach((row, idx) => {
      const rowNum = idx + 2; // Spreadsheet row index (Row 1 is Header)

      const getRowVal = (req: string) => {
        const matchedKey = foundHeaders[req];
        if (matchedKey && row[matchedKey] !== undefined) {
          return String(row[matchedKey] ?? '').trim();
        }
        if (row[req] !== undefined) {
          return String(row[req] ?? '').trim();
        }
        return '';
      };

      const empiVal = getRowVal('empi');
      const firstNameVal = getRowVal('first_name');
      const lastNameVal = getRowVal('last_name');
      const phoneVal = getRowVal('phone_number');
      const practiceNameVal = getRowVal('practice_name');
      const practiceCbVal = getRowVal('practice_callback_number');

      if (!empiVal) {
        errors.push({
          row: rowNum,
          column: foundHeaders['empi'],
          message: `Row ${rowNum}: EMPI is missing.`,
          type: 'FATAL',
        });
        errorCount++;
      }

      if (!firstNameVal) {
        errors.push({
          row: rowNum,
          column: foundHeaders['first_name'],
          message: `Row ${rowNum}: First name is missing.`,
          type: 'FATAL',
        });
        errorCount++;
      }

      if (!lastNameVal) {
        errors.push({
          row: rowNum,
          column: foundHeaders['last_name'],
          message: `Row ${rowNum}: Last name is missing.`,
          type: 'FATAL',
        });
        errorCount++;
      }

      if (!practiceNameVal) {
        errors.push({
          row: rowNum,
          column: foundHeaders['practice_name'],
          message: `Row ${rowNum}: Practice name is missing.`,
          type: 'FATAL',
        });
        errorCount++;
      }

      if (!practiceCbVal) {
        errors.push({
          row: rowNum,
          column: foundHeaders['practice_callback_number'],
          message: `Row ${rowNum}: Practice callback number is missing.`,
          type: 'FATAL',
        });
        errorCount++;
      }

      if (!phoneVal) {
        errors.push({
          row: rowNum,
          column: foundHeaders['phone_number'],
          message: `Row ${rowNum}: Phone number is missing.`,
          type: 'FATAL',
        });
        errorCount++;
        phoneNumbersValid = false;
      } else {
        if (!isValidPhoneNumber(phoneVal)) {
          errors.push({
            row: rowNum,
            column: foundHeaders['phone_number'],
            message: `Row ${rowNum}: Invalid phone number (${phoneVal}).`,
            type: 'FATAL',
          });
          errorCount++;
          phoneNumbersValid = false;
        }

        const cleanPhone = sanitizePhoneNumber(phoneVal);
        if (seenPhones.has(cleanPhone)) {
          errors.push({
            row: rowNum,
            column: foundHeaders['phone_number'],
            message: `Row ${rowNum}: Duplicate phone number detected (${phoneVal}).`,
            type: 'FATAL',
          });
          errorCount++;
          noDuplicatePhones = false;
        } else {
          seenPhones.add(cleanPhone);
        }
      }

      // Per-row 'direct agent' column validation
      if (directAgentHeader && row[directAgentHeader] !== undefined) {
        const rawDirectVal = String(row[directAgentHeader] ?? '').trim().toLowerCase();
        if (rawDirectVal !== '' && rawDirectVal !== 'yes' && rawDirectVal !== 'no') {
          errors.push({
            row: rowNum,
            column: directAgentHeader,
            message: `Row ${rowNum}: Invalid direct agent value ('${row[directAgentHeader]}'). Expected 'yes' or 'no'.`,
            type: 'FATAL',
          });
          errorCount++;
        }
      }
    });
  }

  const fatalErrors = errors.filter((e) => e.type === 'FATAL');

  return {
    isValid: fatalErrors.length === 0,
    totalRows: rawRowCount,
    errorCount,
    warningCount: 0,
    errors,
    summaryChecklist: {
      fileTypeValid: true,
      requiredColumnsPresent,
      recordsFound,
      phoneNumbersValid: phoneNumbersValid && recordsFound && requiredColumnsPresent,
      noDuplicatePhones: noDuplicatePhones && recordsFound && requiredColumnsPresent,
    },
  };
}

/**
 * Validates selected scheduled date and time.
 */
export function validateScheduleTime(scheduleTimeIso: string, timezone?: string): {
  isValid: boolean;
  error?: string;
} {
  if (!scheduleTimeIso) {
    return {
      isValid: false,
      error: 'Please select a schedule calling time.',
    };
  }

  const ianaZone = timezone || 'Asia/Kolkata';
  const selectedDate = localDateTimeInZoneToUtc(scheduleTimeIso, ianaZone);

  if (isNaN(selectedDate.getTime())) {
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(scheduleTimeIso)) {
      return {
        isValid: false,
        error: 'Selected time does not exist in the chosen timezone due to Daylight Saving Time adjustment.',
      };
    }
    return {
      isValid: false,
      error: 'Invalid date/time format.',
    };
  }

  const now = new Date();
  if (selectedDate.getTime() <= now.getTime()) {
    return {
      isValid: false,
      error: 'Scheduled time must be in the future.',
    };
  }

  const minLeadTimeMs = CONFIG.MIN_SCHEDULE_LEAD_TIME_MINUTES * 60 * 1000;
  const leadTimeMs = selectedDate.getTime() - now.getTime();

  if (leadTimeMs < minLeadTimeMs) {
    return {
      isValid: false,
      error: `Please select a schedule time at least ${CONFIG.MIN_SCHEDULE_LEAD_TIME_MINUTES} minutes from now.`,
    };
  }

  return { isValid: true };
}

/**
 * Legacy validator maintained for signature compatibility.
 */
export function validateHumanAgentPhone(): { isValid: boolean } {
  return { isValid: true };
}

