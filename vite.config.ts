import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  base: '/PORTFOLLIO/', // YEH LINE ADD KAREIN. Isse path /PORTFOLLIO/src/main.tsx ban jayega.
})
