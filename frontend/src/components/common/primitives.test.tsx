import { useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AccordionItem } from './Accordion'
import { CursorPagination } from './CursorPagination'
import { DenseDataTable } from './DenseDataTable'
import { Dialog } from './Dialog'
import { TruncatedText } from './TruncatedText'

interface RowValue { id: string; name: string; count: number }
interface TreeRowValue extends RowValue { children?: TreeRowValue[] }
const columns: ColumnDef<RowValue>[] = [
  { accessorKey: 'name', header: '이름', cell: (info) => <TruncatedText value={String(info.getValue())} /> },
  { accessorKey: 'count', header: '건수' },
]

describe('enterprise UI primitives', () => {
  it('renders sortable dense rows and activates the selected row from the keyboard', () => {
    const onActivate = vi.fn()
    render(
      <DenseDataTable
        caption="자산 목록"
        columns={columns}
        data={[{ id: 'b', name: 'Beta', count: 2 }, { id: 'a', name: 'Alpha', count: 1 }]}
        getRowId={(row) => row.id}
        selectedRowId="b"
        expandedRowId="b"
        onRowActivate={onActivate}
        renderExpandedRow={(row) => <p>{row.name} 상세</p>}
      />,
    )
    const table = screen.getByRole('table', { name: '자산 목록' })
    expect(within(table).getByRole('row', { name: /Beta 2/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('Beta 상세')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /이름/ }))
    const bodyRows = within(table).getAllByRole('row').slice(1)
    expect(bodyRows[0]).toHaveTextContent('Alpha')
    fireEvent.keyDown(within(table).getByRole('row', { name: /Alpha 1/ }), { key: 'Enter' })
    expect(onActivate).toHaveBeenCalledWith({ id: 'a', name: 'Alpha', count: 1 })
  })

  it('cycles a sortable header directly through ascending, descending, and none', () => {
    render(
      <DenseDataTable
        caption="필터 목록"
        columns={columns}
        data={[{ id: 'b', name: 'Beta', count: 2 }, { id: 'a', name: 'Alpha', count: 1 }]}
        getRowId={(row) => row.id}
      />,
    )
    const table = screen.getByRole('table', { name: '필터 목록' })
    const header = within(table).getByRole('columnheader', { name: /이름/ })
    expect(header).toHaveAttribute('aria-sort', 'none')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '이름 정렬: 없음' }))
    expect(header).toHaveAttribute('aria-sort', 'ascending')
    expect(within(table).getAllByRole('row')[1]).toHaveTextContent('Alpha')

    fireEvent.click(screen.getByRole('button', { name: '이름 정렬: 오름차순' }))
    expect(header).toHaveAttribute('aria-sort', 'descending')
    expect(within(table).getAllByRole('row')[1]).toHaveTextContent('Beta')

    fireEvent.click(screen.getByRole('button', { name: '이름 정렬: 내림차순' }))
    expect(header).toHaveAttribute('aria-sort', 'none')
    expect(within(table).getAllByRole('row')[1]).toHaveTextContent('Beta')
  })

  it('renders nested TanStack rows and lets an accessible expander collapse a branch', () => {
    const treeColumns: ColumnDef<TreeRowValue>[] = [{
      accessorKey: 'name',
      header: '이름',
      cell: ({ row }) => <div style={{ paddingLeft: `${row.depth * 12}px` }}>
        {row.getCanExpand() && <button
          type="button"
          aria-label={`${row.original.name} 하위 행 ${row.getIsExpanded() ? '접기' : '펼치기'}`}
          aria-expanded={row.getIsExpanded()}
          onClick={row.getToggleExpandedHandler()}
        >{row.getIsExpanded() ? '−' : '+'}</button>}
        {row.original.name}
      </div>,
    }]
    render(<DenseDataTable
      caption="계층 목록"
      columns={treeColumns}
      data={[{ id: 'root', name: 'Root', count: 1, children: [{ id: 'leaf', name: 'Leaf', count: 1 }] }]}
      getRowId={(row) => row.id}
      getSubRows={(row) => row.children}
      initialExpanded
    />)

    expect(screen.getByRole('row', { name: /Leaf/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Root 하위 행 접기' }))
    expect(screen.queryByRole('row', { name: /Leaf/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Root 하위 행 펼치기' }))
    expect(screen.getByRole('row', { name: /Leaf/ })).toBeInTheDocument()
  })

  it('exposes honest loading and empty table states', () => {
    const view = render(<DenseDataTable caption="목록" columns={columns} data={[]} getRowId={(row) => row.id} loading />)
    expect(screen.getByText('데이터를 불러오는 중입니다.')).toBeInTheDocument()
    view.rerender(<DenseDataTable caption="목록" columns={columns} data={[]} getRowId={(row) => row.id} emptyMessage="검색 결과 없음" />)
    expect(screen.getByText('검색 결과 없음')).toBeInTheDocument()
  })

  it('links accordion control and region semantics', () => {
    function Harness() {
      const [expanded, setExpanded] = useState(false)
      return <AccordionItem itemId="asset" title="자산 상세" expanded={expanded} onToggle={() => setExpanded((value) => !value)}>근거 데이터</AccordionItem>
    }
    render(<Harness />)
    const toggle = screen.getByRole('button', { name: /자산 상세/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('region', { name: /자산 상세/ })).toHaveTextContent('근거 데이터')
  })

  it('closes the modal from explicit controls and restores invoking focus', () => {
    function Harness() {
      const [open, setOpen] = useState(false)
      return <><button type="button" onClick={() => setOpen(true)}>열기</button><Dialog open={open} title="상세" onRequestClose={() => setOpen(false)}><button type="button">내부 작업</button></Dialog></>
    }
    render(<Harness />)
    const opener = screen.getByRole('button', { name: '열기' })
    opener.focus(); fireEvent.click(opener)
    expect(screen.getByRole('dialog', { name: '상세' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '상세 닫기' }))
    expect(screen.queryByRole('dialog', { name: '상세' })).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })

  it('provides cursor controls and bounded page-size options', () => {
    const onNext = vi.fn()
    const onPageSizeChange = vi.fn()
    render(<CursorPagination page={2} pageSize={25} canPrevious canNext itemCount={25} onPrevious={vi.fn()} onNext={onNext} onPageSizeChange={onPageSizeChange} />)
    fireEvent.click(screen.getByRole('button', { name: '다음' }))
    fireEvent.change(screen.getByRole('combobox', { name: '페이지 크기' }), { target: { value: '50' } })
    expect(onNext).toHaveBeenCalledOnce()
    expect(onPageSizeChange).toHaveBeenCalledWith(50)
    expect(screen.getByText(/2 페이지/)).toBeInTheDocument()
  })

  it('makes truncated values available to pointer and keyboard users', () => {
    render(<TruncatedText value="urn:li:dataset:very-long-value" />)
    const value = screen.getByLabelText('urn:li:dataset:very-long-value')
    expect(value).toHaveAttribute('title', 'urn:li:dataset:very-long-value')
    expect(value).toHaveAttribute('tabindex', '0')
  })
})
