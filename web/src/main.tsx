import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import '@/state/theme' // applies the persisted theme class before first paint
import App from './app/App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
