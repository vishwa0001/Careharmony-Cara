import { describe, expect, it, vi } from 'vitest';
import { scheduledCallsService } from '../services/scheduledCalls.service';

describe('ScheduledCallsService CSV Export', () => {
  it('should support downloadCampaignCsv method without crashing', async () => {
    const createObjectURL = vi.fn().mockReturnValue('blob:http://localhost/mock');
    const revokeObjectURL = vi.fn();
    window.URL.createObjectURL = createObjectURL;
    window.URL.revokeObjectURL = revokeObjectURL;

    await expect(
      scheduledCallsService.downloadCampaignCsv('camp-101', 'customers_2026_08_29.csv')
    ).resolves.not.toThrow();

    expect(createObjectURL).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalled();
  });
});