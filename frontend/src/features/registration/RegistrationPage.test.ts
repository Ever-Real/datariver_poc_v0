import { describe, expect, it } from 'vitest'
import { supportedContentType, validateProfileFile } from './RegistrationBulkWorkbench'

describe('supportedContentType', () => {
  it('uses a stable server contract when browsers report alternate parquet MIME types', () => {
    expect(supportedContentType({ name: 'assets.parquet', type: 'application/vnd.apache.parquet' }))
      .toBe('application/x-parquet')
  })

  it('rejects executable extensions even when the browser MIME is empty', () => {
    expect(() => supportedContentType({ name: 'payload.exe', type: '' })).toThrow()
  })
})

describe('validateProfileFile', () => {
  it('accepts only CSV for the explicit dataset-description profile', () => {
    expect(() => validateProfileFile(
      { name: 'dataset-description.csv', type: '' },
      'DATASET_DESCRIPTION_CSV_V1',
    )).not.toThrow()
    expect(() => validateProfileFile(
      { name: 'dataset-description.xlsx', type: 'text/csv' },
      'DATASET_DESCRIPTION_CSV_V1',
    )).toThrow(/CSV 파일만/)
  })

  it('does not infer a typed profile from a generic CSV file', () => {
    expect(() => validateProfileFile(
      { name: 'generic.csv', type: 'text/csv' },
      'FORMAT_ONLY_V1',
    )).not.toThrow()
  })
})
