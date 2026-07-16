interface CursorPaginationProps {
  page: number
  pageSize: number
  pageSizeOptions?: readonly number[]
  canPrevious: boolean
  canNext: boolean
  itemCount?: number
  onPrevious: () => void
  onNext: () => void
  onPageSizeChange: (pageSize: number) => void
}

export function CursorPagination({
  page,
  pageSize,
  pageSizeOptions = [25, 50, 100],
  canPrevious,
  canNext,
  itemCount,
  onPrevious,
  onNext,
  onPageSizeChange,
}: CursorPaginationProps) {
  return (
    <nav className="cursor-pagination" aria-label="페이지 탐색">
      <span className="cursor-pagination-summary">
        {itemCount === undefined ? `${page} 페이지` : `${page} 페이지 · 현재 ${itemCount.toLocaleString()}건`}
      </span>
      <label>
        <span>페이지 크기</span>
        <select aria-label="페이지 크기" value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value))}>
          {pageSizeOptions.map((option) => <option key={option} value={option}>{option}</option>)}
        </select>
      </label>
      <button type="button" disabled={!canPrevious} onClick={onPrevious}>이전</button>
      <button type="button" disabled={!canNext} onClick={onNext}>다음</button>
    </nav>
  )
}
