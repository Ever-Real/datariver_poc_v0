import { App } from '../App'
import { PocBanner } from './components/PocBanner'

export function PocApp() {
  return (
    <div className="poc-app">
      <PocBanner />
      <App />
    </div>
  )
}
