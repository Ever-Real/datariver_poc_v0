import { ApiError } from '../api/client'

export function ErrorNotice({ error }: { error?: unknown }) {
  if (!error) return null
  if (error instanceof ApiError) {
    return (
      <div className="notice notice-error" role="alert">
        <strong>{error.problem.title}</strong>
        <span>{error.problem.detail}</span>
        <code>요청 ID: {error.problem.request_id}</code>
      </div>
    )
  }
  return <div className="notice notice-error" role="alert">{error instanceof Error ? error.message : '알 수 없는 오류가 발생했습니다.'}</div>
}
