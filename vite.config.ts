import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'
export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  resolve: { alias: { '@': fileURLToPath(new URL('./frontend', import.meta.url)) } },
  build: {
    outDir: 'assets/ui', emptyOutDir: true,
    lib: { entry: 'frontend/main.tsx', formats: ['iife'], name: 'ToolkitUI', fileName: () => 'ui.js', cssFileName: 'ui' },
  }
})
