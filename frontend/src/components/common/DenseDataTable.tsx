import { Fragment, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import {
  flexRender,
  getCoreRowModel,
  getExpandedRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type ExpandedState,
  type SortingState,
} from '@tanstack/react-table'

interface DenseDataTableProps<T> {
  caption: string
  columns: ColumnDef<T>[]
  data: T[]
  getRowId: (row: T) => string
  getSubRows?: (row: T) => T[] | undefined
  initialExpanded?: boolean
  loading?: boolean
  emptyMessage?: string
  selectedRowId?: string
  expandedRowId?: string
  onRowActivate?: (row: T) => void
  renderExpandedRow?: (row: T) => ReactNode
  className?: string
  fitContainer?: boolean
}

function columnCellClassName(meta: unknown): string | undefined {
  if (!meta || typeof meta !== 'object') return undefined
  const className = (meta as { className?: unknown }).className
  return typeof className === 'string' ? className : undefined
}

export function DenseDataTable<T>({
  caption,
  columns,
  data,
  getRowId,
  getSubRows,
  initialExpanded = false,
  loading = false,
  emptyMessage = '표시할 데이터가 없습니다.',
  selectedRowId,
  expandedRowId,
  onRowActivate,
  renderExpandedRow,
  className,
  fitContainer = false,
}: DenseDataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>([])
  const [expanded, setExpanded] = useState<ExpandedState>(initialExpanded && getSubRows ? true : {})
  const rowElements = useRef(new Map<string, HTMLTableRowElement>())
  // TanStack Table intentionally exposes stateful callbacks that React Compiler does not memoize.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data,
    columns,
    getRowId: (row) => getRowId(row),
    getSubRows,
    state: { sorting, expanded },
    onSortingChange: setSorting,
    onExpandedChange: setExpanded,
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })
  const columnCount = Math.max(1, table.getVisibleLeafColumns().length)
  const activateFromKeyboard = (event: KeyboardEvent<HTMLTableRowElement>, row: T) => {
    if (!onRowActivate || (event.key !== 'Enter' && event.key !== ' ')) return
    event.preventDefault(); onRowActivate(row)
  }

  useEffect(() => {
    if (!selectedRowId) return
    rowElements.current.get(selectedRowId)?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }, [data, selectedRowId])

  return (
    <div className={['dense-table-frame', className].filter(Boolean).join(' ')} aria-busy={loading} aria-label={`${caption} 스크롤 영역`} tabIndex={0}>
      <table className={`dense-data-table ${fitContainer ? 'dense-data-table-fit' : 'dense-data-table-sized'}`}>
        <caption className="sr-only">{caption}</caption>
        <colgroup>
          {table.getVisibleLeafColumns().map((column) => (
            <col key={column.id} width={column.getSize()} />
          ))}
        </colgroup>
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => {
                const sorted = header.column.getIsSorted()
                const canSort = header.column.getCanSort()
                const label = typeof header.column.columnDef.header === 'string'
                  ? header.column.columnDef.header
                  : header.column.id
                const sortingLabel = sorted === 'asc' ? '오름차순' : sorted === 'desc' ? '내림차순' : '없음'
                const cycleSorting = () => {
                  if (sorted === false) {
                    header.column.toggleSorting(false)
                  } else if (sorted === 'asc') {
                    header.column.toggleSorting(true)
                  } else {
                    header.column.clearSorting()
                  }
                }
                return (
                  <th
                    key={header.id}
                    colSpan={header.colSpan}
                    aria-sort={sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : 'none'}
                  >
                    {header.isPlaceholder ? null : canSort ? (
                      <button
                        type="button"
                        aria-label={`${label} 정렬: ${sortingLabel}`}
                        onClick={cycleSorting}
                        title={`${label} 정렬: ${sortingLabel}`}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        <span aria-hidden="true">{sorted === 'asc' ? ' ▲' : sorted === 'desc' ? ' ▼' : ' ↕'}</span>
                      </button>
                    ) : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                )
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {loading && <tr><td className="dense-table-state" colSpan={columnCount}>데이터를 불러오는 중입니다.</td></tr>}
          {!loading && table.getRowModel().rows.length === 0 && <tr><td className="dense-table-state" colSpan={columnCount}>{emptyMessage}</td></tr>}
          {!loading && table.getRowModel().rows.map((row) => (
            <Fragment key={row.id}>
              <tr
                ref={(element) => {
                  if (element) rowElements.current.set(row.id, element)
                  else rowElements.current.delete(row.id)
                }}
                className={`${selectedRowId === row.id ? 'selected' : ''} ${onRowActivate ? 'interactive' : ''}`.trim()}
                aria-selected={selectedRowId === row.id || undefined}
                aria-expanded={renderExpandedRow ? expandedRowId === row.id : undefined}
                tabIndex={onRowActivate ? 0 : undefined}
                onClick={() => onRowActivate?.(row.original)}
                onKeyDown={(event) => activateFromKeyboard(event, row.original)}
              >
                {row.getVisibleCells().map((cell) => <td key={cell.id} className={columnCellClassName(cell.column.columnDef.meta)}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}
              </tr>
              {renderExpandedRow && expandedRowId === row.id && (
                <tr className="dense-table-expanded-row">
                  <td colSpan={columnCount}>{renderExpandedRow(row.original)}</td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}
