import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import { mockPlugin } from './vite-plugin-mock.js'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    // 开发环境 Mock 拦截插件：
    // 拦截 /api/auth/* 请求，直接返回 contracts/mock/ 中的 JSON 数据
    // 仅在 dev server (npm run dev) 生效，不影响 production build
    mockPlugin(),
  ],

  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },

  server: {
    proxy: {
      '/api': {
        // 非 Mock 的 /api/* 请求仍透传到后端
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
