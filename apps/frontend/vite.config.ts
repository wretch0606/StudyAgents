import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],

  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },

  server: {
    proxy: {
      '/api': {
        // 转发到 Docker Compose 暴露的真实后端（compose.yml: "8080:8000"）
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
})
