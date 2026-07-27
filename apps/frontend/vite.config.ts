import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import { viteMockServe } from 'vite-plugin-mock'
import { mockPlugin } from './vite-plugin-mock.js'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    // 开发环境 Mock 拦截插件（auth 相关）：
    // 拦截 /api/auth/* 请求，直接返回 contracts/mock/ 中的 JSON 数据
    // 仅在 dev server (npm run dev) 生效，不影响 production build
    mockPlugin(),
    // 网络级 Mock 拦截（chat / 训练 / 错题本等业务 API）：
    // 读取 mock/ 目录下的 Mock 文件，使用 mockjs 生成数据
    // 默认仅在 dev server 生效，production build 自动禁用
    viteMockServe({
      mockPath: 'mock',
    }),
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
