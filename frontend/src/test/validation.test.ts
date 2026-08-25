import { describe, expect, it } from "vitest";
import { mapApiRecordToScheduledUpload, scheduledCallsService } from "../services/scheduledCalls.service";
import type { ScheduledUpload } from "../types/scheduledCalls.types";
import {
  generateSampleCsvContent,
  SAMPLE_CUSTOMER_RECORDS,
} from "../utils/sampleCsvGenerator";
import {
  isValidPhoneNumber,
  sanitizePhoneNumber,
  validateCsvFile,
  validateFileMetadata,
  validateScheduleTime,
  validateSheetContent,
} from "../utils/scheduledCalls.validation";
import { getAvailableActions } from "../utils/statusActions";
import {
  getTimezoneOffsetDisplay,
  getTimezoneOptions,
  localDateTimeInZoneToUtc,
} from "../utils/timezone";

describe("Scheduled Calls Validation & Feature Suite", () => {
  describe("Sample CSV Generator", () => {
    it("creates a valid CSV content string with required headers and records", () => {
      const csvContent = generateSampleCsvContent();
      const lines = csvContent.split("\n");

      expect(lines[0]).toBe(
        "empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number",
      );
      expect(lines.length).toBe(SAMPLE_CUSTOMER_RECORDS.length + 1);
      expect(lines[1]).toContain(
        "TESTPT-0000,Robert,Alderman,Male,15550101001,Sample Practice Group,5555550100",
      );
    });

    it("sample records pass Careharmony spreadsheet content validation", () => {
      const parsedData = {
        headers: [
          "empi",
          "first_name",
          "last_name",
          "gender",
          "phone_number",
          "practice_name",
          "practice_callback_number",
        ],
        rows: SAMPLE_CUSTOMER_RECORDS,
        rawRowCount: SAMPLE_CUSTOMER_RECORDS.length,
      };

      const result = validateSheetContent(parsedData);
      expect(result.isValid).toBe(true);
      expect(result.totalRows).toBe(SAMPLE_CUSTOMER_RECORDS.length);
      expect(result.errors).toHaveLength(0);
    });

    it("accepts headers with UTF-8 BOM (\\ufeff) and leading/trailing whitespace", () => {
      const parsedData = {
        headers: [
          "\ufeffempi",
          " first_name ",
          "last_name\t",
          "gender",
          "phone_number",
          "practice_name",
          "practice_callback_number",
        ],
        rows: SAMPLE_CUSTOMER_RECORDS,
        rawRowCount: SAMPLE_CUSTOMER_RECORDS.length,
      };

      const result = validateSheetContent(parsedData);
      expect(result.isValid).toBe(true);
      expect(result.totalRows).toBe(SAMPLE_CUSTOMER_RECORDS.length);
    });

    it("rejects missing required headers and reports exact missing column list", () => {
      const parsedData = {
        headers: ["empi", "first_name", "last_name"],
        rows: [],
        rawRowCount: 0,
      };

      const result = validateSheetContent(parsedData);
      expect(result.isValid).toBe(false);
      expect(result.errors[0].message).toContain(
        "Missing required column: gender, phone_number, practice_name, practice_callback_number",
      );
    });

    it("rejects old customerName/phoneNumber schema", () => {
      const parsedData = {
        headers: ["customerName", "phoneNumber"],
        rows: [{ customerName: "John Doe", phoneNumber: "+14155550101" }],
        rawRowCount: 1,
      };

      const result = validateSheetContent(parsedData);
      expect(result.isValid).toBe(false);
      expect(result.errors[0].message).toContain(
        "Missing required column: empi, first_name, last_name, gender, practice_name, practice_callback_number",
      );
    });
  });

  describe("Programmatic CSV-Only File Validation (validateCsvFile)", () => {
    it("accepts valid CSV files regardless of case", () => {
      const mockCsv1 = new File(
        [
          "empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number\nTESTPT-0000,Robert,Alderman,Male,15550101001,Sample Practice Group,5555550100",
        ],
        "patients.csv",
        { type: "text/csv" },
      );
      const mockCsv2 = new File(
        [
          "empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number\nTESTPT-0000,Karen,Whitfield,Female,15550101002,Sample Practice Group,5555550100",
        ],
        "customers.CSV",
        { type: "text/csv" },
      );

      expect(validateCsvFile(mockCsv1).valid).toBe(true);
      expect(validateCsvFile(mockCsv2).valid).toBe(true);
    });

    it("rejects non-CSV files (xlsx, xls, json, txt, pdf, compound extensions)", () => {
      const invalidFiles = [
        new File(["dummy"], "patients.xlsx", {
          type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }),
        new File(["dummy"], "patients.xls", {
          type: "application/vnd.ms-excel",
        }),
        new File(["dummy"], "patients.json", { type: "application/json" }),
        new File(["dummy"], "patients.txt", { type: "text/plain" }),
        new File(["dummy"], "document.pdf", { type: "application/pdf" }),
        new File(["dummy"], "patients.csv.xlsx", {
          type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }),
        new File(["dummy"], "patients.csv.txt", { type: "text/plain" }),
      ];

      invalidFiles.forEach((file) => {
        const res = validateCsvFile(file);
        expect(res.valid).toBe(false);
        expect(res.error).toBe(
          "Only CSV files are supported. Please upload a .csv file.",
        );
      });
    });
  });

  describe("Status Action Rules Matrix", () => {
    it("returns correct action rules for CANCELLED status", () => {
      const actions = getAvailableActions("CANCELLED");
      expect(actions.canView).toBe(true);
      expect(actions.canReschedule).toBe(true);
      expect(actions.canCancel).toBe(false);
      expect(actions.canReupload).toBe(false);
    });

    it("returns correct action rules for FAILED and VALIDATION_FAILED status", () => {
      const failedActions = getAvailableActions("FAILED");
      expect(failedActions.canView).toBe(true);
      expect(failedActions.canReupload).toBe(true);
      expect(failedActions.canReschedule).toBe(false);
      expect(failedActions.canCancel).toBe(false);

      const valFailedActions = getAvailableActions("VALIDATION_FAILED");
      expect(valFailedActions.canReupload).toBe(true);
    });

    it("returns correct action rules for SCHEDULED status", () => {
      const actions = getAvailableActions("SCHEDULED");
      expect(actions.canView).toBe(true);
      expect(actions.canCancel).toBe(true);
      expect(actions.canReschedule).toBe(false);
      expect(actions.canReupload).toBe(false);
    });
  });

  describe("Campaign API Contract Mapping", () => {
    it("maps backend PENDING and RUNNING states to UI statuses", () => {
      expect(mapApiRecordToScheduledUpload({ campaignId: "c1", status: "PENDING" }).status).toBe("SCHEDULED");
      expect(mapApiRecordToScheduledUpload({ campaignId: "c2", status: "RUNNING" }).status).toBe("PROCESSING");
    });

    it("preserves campaign outcome summary from the backend", () => {
      const mapped = mapApiRecordToScheduledUpload({
        campaignId: "c1", status: "COMPLETED", patientCount: 2,
        summary: { total: 2, pending: 0, inProgress: 0, completed: 2, callSetupFailed: 0, dispositions: { "Identity Confirmed": 2 } },
      });
      expect(mapped.summary?.completed).toBe(2);
      expect(mapped.summary?.dispositions["Identity Confirmed"]).toBe(2);
    });
  });

  describe("Timezone Utilities", () => {
    it("provides timezone options with offset displays", () => {
      const options = getTimezoneOptions();
      expect(options.length).toBeGreaterThan(0);
      const kolkata = options.find(
        (o) => o.iana === "Asia/Kolkata" || o.iana === "Asia/Calcutta",
      );
      expect(kolkata).toBeDefined();
      expect(kolkata?.offsetDisplay).toContain("UTC+05:30");
    });

    it("handles DST-aware timezones cleanly", () => {
      const nyOffset = getTimezoneOffsetDisplay("America/New_York");
      expect(nyOffset).toMatch(/^UTC[\+\-]\d{2}:\d{2}$/);
    });

    it("converts selected wall-clock time using the selected IANA timezone", () => {
      const utc = localDateTimeInZoneToUtc("2030-08-25T10:00", "America/New_York");
      expect(utc.toISOString()).toContain("T14:00:00.000Z");
    });
  });

  describe("Service Layer Lineage & Reschedule / Re-upload Workflows", () => {
    it("reschedules CANCELLED record without mutating original status", async () => {
      const list = await scheduledCallsService.getScheduledUploads();
      const cancelledItem = list.find((u) => u.status === "CANCELLED");
      expect(cancelledItem).toBeDefined();

      const futureTime = new Date(Date.now() + 24 * 3600 * 1000).toISOString();
      const newRecord = await scheduledCallsService.rescheduleCancelledRecord(
        cancelledItem!.id,
        futureTime,
        "America/New_York",
      );

      expect(newRecord.status).toBe("SCHEDULED");
      expect(newRecord.originalRecordId).toBe(cancelledItem!.id);
      expect(newRecord.timezone).toBe("America/New_York");

      // Original record must remain CANCELLED
      const updatedOriginal =
        await scheduledCallsService.getScheduledUploadDetails(
          cancelledItem!.id,
        );
      expect(updatedOriginal?.status).toBe("CANCELLED");
      expect(updatedOriginal?.rescheduledToId).toBe(newRecord.id);
    });

    it("re-uploads FAILED record without mutating original status", async () => {
      const list = await scheduledCallsService.getScheduledUploads();
      const failedItem = list.find((u) => u.status === "FAILED");
      expect(failedItem).toBeDefined();

      const dummyFile = new File(
        ["customerName,phoneNumber\nJohn,+14155550101"],
        "replacement.csv",
        { type: "text/csv" },
      );
      const futureTime = new Date(Date.now() + 12 * 3600 * 1000).toISOString();

      const newRecord = await scheduledCallsService.reuploadFailedRecord(
        failedItem!.id,
        {
          file: dummyFile,
          scheduledAt: futureTime,
          timezone: "Europe/London",
          customerCount: 1,
          validationSummary: {
            isValid: true,
            totalRows: 1,
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
      );

      expect(newRecord.status).toBe("SCHEDULED");
      expect(newRecord.fileName).toBe("replacement.csv");
      expect(newRecord.originalRecordId).toBe(failedItem!.id);

      // Original record must remain FAILED
      const updatedOriginal =
        await scheduledCallsService.getScheduledUploadDetails(failedItem!.id);
      expect(updatedOriginal?.status).toBe("FAILED");
      expect(updatedOriginal?.replacedById).toBe(newRecord.id);
    });

    it("defensively rejects non-CSV files at service layer before API call", async () => {
      const invalidFile = new File(
        ["dummy"],
        "sample_customer_calling_list.xlsx",
        {
          type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
      );
      const futureTime = new Date(Date.now() + 12 * 3600 * 1000).toISOString();

      await expect(
        scheduledCallsService.scheduleCustomerSheet({
          file: invalidFile,
          scheduledAt: futureTime,
          timezone: "Asia/Kolkata",
          customerCount: 5,
          validationSummary: {
            isValid: true,
            totalRows: 5,
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
        }),
      ).rejects.toThrow(
        "Only CSV files are supported. Please upload a .csv file.",
      );
    });
  });

  describe("File Metadata Validation", () => {
    it("rejects null or missing file", () => {
      const result = validateFileMetadata(null);
      expect(result.isValid).toBe(false);
      expect(result.errors[0].message).toBe("Please select a customer sheet.");
    });

    it("rejects unsupported file extensions (xlsx, pdf, txt, etc)", () => {
      const mockXlsx = new File(["dummy"], "customers.xlsx", {
        type: "application/vnd.ms-excel",
      });
      const result = validateFileMetadata(mockXlsx);
      expect(result.isValid).toBe(false);
      expect(result.errors[0].message).toBe(
        "Only CSV files are supported. Please upload a .csv file.",
      );
    });

    it("accepts valid .csv files", () => {
      const mockCsv = new File(
        [
          "empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number\nTESTPT-0000,Robert,Alderman,Male,15550101001,Sample Practice Group,5555550100",
        ],
        "leads.csv",
        { type: "text/csv" },
      );
      const result = validateFileMetadata(mockCsv);
      expect(result.isValid).toBe(true);
    });

    it("produces a non-fatal warning when duplicate filename is uploaded", () => {
      const existing: ScheduledUpload[] = [
        {
          id: "1",
          fileName: "leads.csv",
          fileSize: 100,
          customerCount: 10,
          scheduledAt: new Date().toISOString(),
          timezone: "Asia/Kolkata",
          uploadedAt: new Date().toISOString(),
          status: "SCHEDULED",
        },
      ];

      const mockFile = new File(
        [
          "empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number\nTESTPT-0000,Robert,Alderman,Male,15550101001,Sample Practice Group,5555550100",
        ],
        "LEADS.CSV",
        { type: "text/csv" },
      );
      const result = validateFileMetadata(mockFile, existing);
      expect(result.isValid).toBe(true);
      expect(result.warnings).toHaveLength(1);
    });
  });

  describe("Phone Number Validation", () => {
    it("sanitizes formatted phone numbers", () => {
      expect(sanitizePhoneNumber("+91 (987) 654-3210")).toBe("+919876543210");
    });

    it("validates correct 10-15 digit E.164 and international numbers", () => {
      expect(isValidPhoneNumber("+919876543210")).toBe(true);
      expect(isValidPhoneNumber("9876543210")).toBe(true);
    });
  });

  describe("Schedule Time Validation", () => {
    it("rejects past schedule time", () => {
      const pastDate = new Date(Date.now() - 3600 * 1000).toISOString();
      const result = validateScheduleTime(pastDate);
      expect(result.isValid).toBe(false);
      expect(result.error).toBe("Scheduled time must be in the future.");
    });

    it("accepts valid schedule time beyond lead time", () => {
      const validFuture = new Date(Date.now() + 15 * 60 * 1000).toISOString();
      const result = validateScheduleTime(validFuture);
      expect(result.isValid).toBe(true);
    });
  });
});
