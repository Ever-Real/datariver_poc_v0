export function UnavailableCapability({ title, reason }: { title: string; reason: string }) {
  return (
    <section className="panel unavailable-capability" role="status">
      <span aria-hidden="true">!</span>
      <div>
        <h2>{title}</h2>
        <p>{reason}</p>
      </div>
    </section>
  )
}
