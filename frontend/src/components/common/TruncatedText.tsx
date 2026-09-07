export function TruncatedText({ value, className = '' }: { value: string; className?: string }) {
  return (
    <span
      className={`truncated-text ${className}`.trim()}
      title={value}
      aria-label={value}
      tabIndex={0}
    >
      {value}
    </span>
  )
}
