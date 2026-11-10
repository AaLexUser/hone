import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// HONE_WEB_BASE serves the app under a path prefix, such as /hone/ behind a reverse proxy.
export default defineConfig({
  base: process.env.HONE_WEB_BASE ?? '/',
  plugins: [react(), tailwindcss()],
})
