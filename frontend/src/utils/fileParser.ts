import * as XLSX from 'xlsx';

export interface ParsedSheetData {
  headers: string[];
  rows: Record<string, any>[];
  rawRowCount: number;
}

export async function parseCustomerSheet(file: File): Promise<ParsedSheetData> {
  const data = await file.arrayBuffer();
  const workbook = XLSX.read(data, { type: 'array' });
  const firstSheetName = workbook.SheetNames[0];

  if (!firstSheetName) {
    throw new Error('Spreadsheet file contains no worksheets.');
  }

  const worksheet = workbook.Sheets[firstSheetName];
  const rawRows: Record<string, any>[] = XLSX.utils.sheet_to_json(worksheet, {
    defval: '',
    raw: false,
  });

  if (rawRows.length === 0) {
    return { headers: [], rows: [], rawRowCount: 0 };
  }

  // Extract keys and normalize: strip UTF-8 BOM (\ufeff) and leading/trailing whitespace
  const firstRowKeys = Object.keys(rawRows[0] || {});
  const headers = firstRowKeys.map((h) => h.replace(/^\ufeff/, '').trim());

  // Build mapped rows with cleaned header keys
  const cleanedRows = rawRows.map((row) => {
    const cleanRow: Record<string, any> = {};
    firstRowKeys.forEach((key) => {
      const cleanKey = key.replace(/^\ufeff/, '').trim();
      cleanRow[cleanKey] = String(row[key] ?? '').trim();
    });
    return cleanRow;
  });

  return {
    headers,
    rows: cleanedRows,
    rawRowCount: cleanedRows.length,
  };
}
