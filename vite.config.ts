import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/PORTFOLLIO/', // Aapki repository ka naam yahan hona chahiye
})
