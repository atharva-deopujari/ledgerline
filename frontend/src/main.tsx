import Daily from '@daily-co/daily-js'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles/fonts.css'
import './styles/tokens.css'
import './styles/app.css'

// The call hook reads daily-js off the global so a test can swap in a fake.
globalThis.Daily = Daily as never

function render() {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

// `?mock=1` replays a scripted call instead of joining a room. Checked inline and
// imported lazily so none of the mock ships in the normal path.
if (new URLSearchParams(window.location.search).get('mock') === '1') {
  void import('./mock/install').then(({ installMock }) => {
    installMock()
    render()
  })
} else {
  render()
}
