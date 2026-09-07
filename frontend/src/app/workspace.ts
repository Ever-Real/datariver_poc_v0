const WORKSPACE_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function workspaceFromLocation(href = window.location.href): string {
  const candidate = new URL(href).searchParams.get('workspace')?.trim() ?? ''
  return WORKSPACE_ID.test(candidate) ? candidate : ''
}

export function defaultWorkspaceSelection(currentWorkspace: string, serverDefault: string | undefined): string {
  if (currentWorkspace) return currentWorkspace
  const candidate = serverDefault?.trim() ?? ''
  return WORKSPACE_ID.test(candidate) ? candidate : ''
}
