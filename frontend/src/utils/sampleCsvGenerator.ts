export const SAMPLE_CUSTOMER_RECORDS = [
  {
    empi: 'TESTPT-0000',
    first_name: 'Robert',
    last_name: 'Alderman',
    gender: 'Male',
    phone_number: '15550101001',
    practice_name: 'Sample Practice Group',
    practice_callback_number: '5555550100',
  },
  {
    empi: 'TESTPT-0000',
    first_name: 'Karen',
    last_name: 'Whitfield',
    gender: 'Female',
    phone_number: '15550101002',
    practice_name: 'Sample Practice Group',
    practice_callback_number: '5555550100',
  },
  {
    empi: 'TESTPT-0000',
    first_name: 'Linda',
    last_name: 'Ostrander',
    gender: 'Female',
    phone_number: '15550101003',
    practice_name: 'Sample Practice Group',
    practice_callback_number: '5555550100',
  },
  {
    empi: 'TESTPT-0000',
    first_name: 'James',
    last_name: 'Dunmore',
    gender: 'Male',
    phone_number: '15550101004',
    practice_name: 'Sample Practice Group',
    practice_callback_number: '5555550100',
  },
  {
    empi: 'TESTPT-0000',
    first_name: 'Patricia',
    last_name: 'Renquist',
    gender: 'Female',
    phone_number: '15550101005',
    practice_name: 'Sample Practice Group',
    practice_callback_number: '5555550100',
  },
];

/**
 * Escapes a field for CSV format if it contains commas, quotes, or newlines.
 */
function escapeCsvField(val: string): string {
  if (val.includes(',') || val.includes('"') || val.includes('\n')) {
    return `"${val.replace(/"/g, '""')}"`;
  }
  return val;
}

/**
 * Generates unified sample CSV string content.
 */
export function generateSampleCsvContent(): string {
  const headers = [
    'empi',
    'first_name',
    'last_name',
    'gender',
    'phone_number',
    'practice_name',
    'practice_callback_number',
  ];
  const lines = [headers.join(',')];

  SAMPLE_CUSTOMER_RECORDS.forEach((rec) => {
    const row = [
      escapeCsvField(rec.empi),
      escapeCsvField(rec.first_name),
      escapeCsvField(rec.last_name),
      escapeCsvField(rec.gender),
      escapeCsvField(rec.phone_number),
      escapeCsvField(rec.practice_name),
      escapeCsvField(rec.practice_callback_number),
    ];
    lines.push(row.join(','));
  });

  return lines.join('\n');
}

/**
 * Triggers a browser download of the sample customer sheet .csv file.
 */
export function downloadSampleCsv(
  filename = 'sample_customer_calling_list.csv'
): void {
  const csvContent = generateSampleCsvContent();
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);

  const link = document.createElement('a');
  link.setAttribute('href', url);
  link.setAttribute('download', filename);
  link.style.visibility = 'hidden';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
