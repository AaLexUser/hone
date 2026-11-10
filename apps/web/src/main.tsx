import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { StoreProvider } from './store.tsx'
import { BASE } from './lib/url'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <StoreProvider>
      <BrowserRouter basename={BASE}>
        <App />
      </BrowserRouter>
    </StoreProvider>
  </StrictMode>,
)
