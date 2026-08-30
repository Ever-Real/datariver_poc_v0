import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { FlowCanvas } from './FlowCanvas'
import { WorkflowStepper } from './WorkflowStepper'

describe('enterprise workflow primitives', () => {
  it('marks the canonical current step and prevents future-stage inspection by default', () => {
    const onSelect = vi.fn()
    render(
      <WorkflowStepper
        currentIndex={1}
        onSelect={onSelect}
        steps={[
          { id: 'request', label: '요청 상세' },
          { id: 'review', label: '검토 및 영향도' },
          { id: 'test', label: '테스트 및 결과' },
          { id: 'approval', label: '최종 승인' },
        ]}
      />,
    )

    expect(screen.getByRole('button', { name: /검토 및 영향도/ })).toHaveAttribute('aria-current', 'step')
    expect(screen.queryByRole('button', { name: /테스트 및 결과/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /요청 상세/ }))
    expect(onSelect).toHaveBeenCalledWith(0)
  })

  it('keeps an accessible, non-zero graph surface when authorized graph data is empty', () => {
    render(
      <FlowCanvas
        ariaLabel="영향도 그래프"
        nodes={[]}
        edges={[]}
        emptyTitle="인가된 계보가 없습니다."
        emptyDescription="대상을 선택하세요."
      />,
    )

    const canvas = screen.getByRole('region', { name: '영향도 그래프' })
    expect(canvas).toHaveClass('flow-canvas-height-420')
    expect(canvas).not.toHaveAttribute('style')
    expect(screen.getByLabelText('인가된 계보가 없습니다., 대상을 선택하세요.')).toBeInTheDocument()
  })

  it.each([1, 5, 50, 200])(
    'renders %i graph nodes with external presentation classes',
    (nodeCount) => {
      const nodes = Array.from({ length: nodeCount }, (_, index) => ({
        id: `node-${index}`,
        label: `Node ${index}`,
        kind: index % 2 === 0 ? 'source' as const : 'target' as const,
      }))
      const { container, unmount } = render(
        <FlowCanvas
          ariaLabel={`${nodeCount} node graph`}
          nodes={nodes}
          edges={[]}
          showMiniMap={false}
        />,
      )

      expect(container.querySelectorAll('.flow-canvas-node')).toHaveLength(nodeCount)
      expect(container.querySelector('.flow-canvas-node')).toHaveClass('flow-canvas-node')
      expect(container.querySelector('.flow-canvas-node')?.getAttribute('style') ?? '')
        .not.toMatch(/background|border|padding|font/)
      unmount()
    },
  )

  it.each([
    [420, 'flow-canvas-height-420'],
    [430, 'flow-canvas-height-430'],
    [480, 'flow-canvas-height-480'],
  ] as const)('maps the %i pixel canvas height to a finite class', (height, className) => {
    const { unmount } = render(
      <FlowCanvas ariaLabel={`${height} pixel graph`} nodes={[]} edges={[]} height={height} />,
    )

    expect(screen.getByRole('region', { name: `${height} pixel graph` })).toHaveClass(className)
    unmount()
  })
})
