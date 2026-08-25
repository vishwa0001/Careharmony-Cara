import { downloadSampleCsv, generateSampleCsvContent, SAMPLE_CUSTOMER_RECORDS } from './sampleCsvGenerator';

export { SAMPLE_CUSTOMER_RECORDS, generateSampleCsvContent };

/**
 * Legacy wrapper for downloading sample CSV template.
 */
export function downloadSampleExcel(filename = 'sample_customer_calling_list.csv'): void {
  downloadSampleCsv(filename);
}

/**
 * Legacy wrapper for sample workbook compatibility.
 */
export function generateSampleExcelWorkbook(): any {
  return {
    SheetNames: ['Customer List'],
    Sheets: {
      'Customer List': {},
    },
  };
}
