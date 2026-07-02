import { defineConfig } from 'vite';

export default defineConfig({
  root: '.',
  build: {
    outDir: '../backend/static/assets',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: 'src/main.js',
      },
      output: {
        entryFileNames: '[name].js',
        assetFileNames: '[name][extname]',
      },
    },
  },
});
