import { describe, expect, it } from "vitest";
import {
  generateSampleCsvContent,
  SAMPLE_CUSTOMER_RECORDS,
} from "../utils/sampleCsvGenerator";
import {
  normalizeHumanAgentPhone,
  validateCsvFile,
  validateHumanAgentPhone,
  validateScheduleTime,
  validateSheetContent,
} from "../utils/scheduledCalls.validation";
import {
  getQuickPresetWallClock,
  getTomorrowPresetWallClock,
  localDateTimeInZoneToUtc,
} from "../utils/timezone";

describe("Scheduled Calls Validation & Feature Suite", () => {
  describe("Sample CSV Generator Unified Template", () => {
    it("generates standard CSV template without 'direct agent' column", () => {
      const csv = generateSampleCsvContent();
      const lines = csv.split("\n");
      expect(lines[0]).toBe(
        "empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number,provider_name",
      );
      expect(csv).not.toContain("direct agent");
      expect(csv).not.toContain("human_agent_phone_number");
    });

    it("sample records pass spreadsheet content validation", () => {
      const parsedData = {
        headers: [
          "empi",
          "first_name",
          "last_name",
          "gender",
          "phone_number",
          "practice_name",
          "practice_callback_number",
          "provider_name",
        ],
        rows: [...SAMPLE_CUSTOMER_RECORDS],
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
        rows: [...SAMPLE_CUSTOMER_RECORDS],
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
  });

  describe("Programmatic CSV-Only File Validation (validateCsvFile)", () => {
    it("accepts valid CSV files regardless of case", () => {
      const mockCsv1 = new File(
        [
          "empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number,direct agent\nTESTPT-0000,Robert,Alderman,Male,15550101001,Sample Practice Group,5555550100,yes",
        ],
        "patients.csv",
        { type: "text/csv" },
      );
      const mockCsv2 = new File(
        [
          "empi,first_name,last_name,gender,phone_number,practice_name,practice_callback_number,direct agent\nTESTPT-0000,Karen,Whitfield,Female,15550101002,Sample Practice Group,5555550100,no",
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

  describe("Direct Agent Setting & Phone Validation", () => {
    it("accepts CSVs with or without 'direct agent' column (column is ignored for campaign-level toggle)", () => {
      const parsedDataWithCol = {
        headers: [
          "empi",
          "first_name",
          "last_name",
          "gender",
          "phone_number",
          "practice_name",
          "practice_callback_number",
          "direct agent",
        ],
        rows: [
          { empi: "T1", first_name: "A", last_name: "B", gender: "Male", phone_number: "+18145551111", practice_name: "P", practice_callback_number: "+18145550000", "direct agent": "yes" },
          { empi: "T2", first_name: "C", last_name: "D", gender: "Female", phone_number: "+18145552222", practice_name: "P", practice_callback_number: "+18145550000", "direct agent": "maybe" },
        ],
        rawRowCount: 2,
      };

      const result = validateSheetContent(parsedDataWithCol);
      expect(result.isValid).toBe(true);
      expect(result.errors).toHaveLength(0);
    });

    it("accepts CSVs with optional 'provider_name' column", () => {
      const parsedDataWithProvider = {
        headers: [
          "empi",
          "first_name",
          "last_name",
          "gender",
          "phone_number",
          "practice_name",
          "practice_callback_number",
          "provider_name",
        ],
        rows: [
          { empi: "T1", first_name: "Robert", last_name: "Alderman", gender: "Male", phone_number: "+18145551111", practice_name: "Sample Practice Group", practice_callback_number: "+18145550000", provider_name: "Dr. Gregory House" },
          { empi: "T2", first_name: "Karen", last_name: "Whitfield", gender: "Female", phone_number: "+18145552222", practice_name: "Sample Practice Group", practice_callback_number: "+18145550000", provider_name: "" },
        ],
        rawRowCount: 2,
      };

      const result = validateSheetContent(parsedDataWithProvider);
      expect(result.isValid).toBe(true);
      expect(result.errors).toHaveLength(0);
    });

    it("validates human agent phone number format correctly", () => {
      expect(validateHumanAgentPhone("").isValid).toBe(false);
      expect(validateHumanAgentPhone("+15822671755").isValid).toBe(true);
      expect(validateHumanAgentPhone("+1 (582) 267-1755").isValid).toBe(true);
      expect(validateHumanAgentPhone("123").isValid).toBe(false);
    });
  });

  describe("OS/Browser-Independent Timezone Mathematics & Validation", () => {
    it("converts wall-clock strings to exact UTC Date in Asia/Kolkata (+05:30)", () => {
      const wallClock = "2026-08-30T22:38";
      const dateUtc = localDateTimeInZoneToUtc(wallClock, "Asia/Kolkata");
      expect(dateUtc.toISOString()).toBe("2026-08-30T17:08:00.000Z");
    });

    it("converts wall-clock strings to exact UTC Date in America/New_York (EDT UTC-04:00)", () => {
      const wallClock = "2026-08-30T22:38";
      const dateUtc = localDateTimeInZoneToUtc(wallClock, "America/New_York");
      expect(dateUtc.toISOString()).toBe("2026-08-31T02:38:00.000Z");
    });

    it("converts wall-clock strings to exact UTC Date in UTC", () => {
      const wallClock = "2026-08-30T22:38";
      const dateUtc = localDateTimeInZoneToUtc(wallClock, "UTC");
      expect(dateUtc.toISOString()).toBe("2026-08-30T22:38:00.000Z");
    });

    it("rejects non-existent DST spring-forward wall-clock times with clear error", () => {
      // 2026-03-08 02:30 in America/New_York does not exist due to DST spring forward
      const springForwardWall = "2026-03-08T02:30";
      const check = validateScheduleTime(springForwardWall, "America/New_York");
      expect(check.isValid).toBe(false);
      expect(check.error).toBe(
        "Selected time does not exist in the chosen timezone due to Daylight Saving Time adjustment.",
      );
    });

    it("accepts valid future wall-clock time in Asia/Kolkata", () => {
      const futureWall = "2030-01-01T10:00";
      const check = validateScheduleTime(futureWall, "Asia/Kolkata");
      expect(check.isValid).toBe(true);
    });

    it("rejects past wall-clock time in Asia/Kolkata", () => {
      const pastWall = "2020-01-01T10:00";
      const check = validateScheduleTime(pastWall, "Asia/Kolkata");
      expect(check.isValid).toBe(false);
      expect(check.error).toBe("Scheduled time must be in the future.");
    });

    it("generates timezone-aware quick preset +15 Mins", () => {
      const baseDate = new Date("2026-08-30T17:00:00Z"); // 22:30 IST
      const preset = getQuickPresetWallClock(15, "Asia/Kolkata", baseDate);
      expect(preset).toBe("2026-08-30T22:45");
    });

    it("generates timezone-aware Tomorrow preset advancing 1 calendar day", () => {
      const preset = getTomorrowPresetWallClock("Asia/Kolkata", "2026-08-30T22:38");
      expect(preset).toBe("2026-08-31T22:38");
    });
  });

  describe("Human Agent Phone Validation & Normalization Suite", () => {
    it("rejects empty or whitespace phone strings", () => {
      expect(validateHumanAgentPhone("").isValid).toBe(false);
      expect(validateHumanAgentPhone("   ").isValid).toBe(false);
      expect(validateHumanAgentPhone("").error).toBe("Human agent phone number is required.");
    });

    it("accepts valid E.164 phone numbers", () => {
      expect(validateHumanAgentPhone("+18148316822").isValid).toBe(true);
      expect(validateHumanAgentPhone("+15822671755").isValid).toBe(true);
      expect(validateHumanAgentPhone("+441234567890").isValid).toBe(true);
    });

    it("accepts valid 10-digit and 11-digit numbers", () => {
      expect(validateHumanAgentPhone("8148316822").isValid).toBe(true);
      expect(validateHumanAgentPhone("(814) 831-6822").isValid).toBe(true);
      expect(validateHumanAgentPhone("18148316822").isValid).toBe(true);
    });

    it("rejects invalid phone formats or lengths", () => {
      expect(validateHumanAgentPhone("123").isValid).toBe(false);
      expect(validateHumanAgentPhone("not-a-number").isValid).toBe(false);
    });

    it("normalizes phone formats correctly to E.164", () => {
      expect(normalizeHumanAgentPhone("+18148316822")).toBe("+18148316822");
      expect(normalizeHumanAgentPhone("8148316822")).toBe("+18148316822");
      expect(normalizeHumanAgentPhone("(814) 831-6822")).toBe("+18148316822");
      expect(normalizeHumanAgentPhone("18148316822")).toBe("+18148316822");
    });
  });
});
