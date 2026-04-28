import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
        configure: (proxy) => {
          // Suppress ALL proxy errors silently
          proxy.on('error', () => {});
          proxy.on('proxyReqWs', (_proxyReq, _req, socket) => {
            socket.on('error', () => {});
          });
        },
      },
    },
  },
  // Silence internal logger for proxy errors
  customLogger: (() => {
    const logger = {
      info: (...args) => console.log(...args),
      warn: (...args) => console.warn(...args),
      warnOnce: (...args) => console.warn(...args),
      error: (msg, ...args) => {
        // Suppress ws proxy error noise
        if (typeof msg === 'string' && msg.includes('ws proxy')) return;
        console.error(msg, ...args);
      },
      clearScreen: () => {},
      hasErrorLogged: () => false,
      hasWarned: false,
    };
    return logger;
  })(),
})
