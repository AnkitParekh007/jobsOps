import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({base:'/jobsOps/',plugins:[react()],ssr:{noExternal:['react-helmet-async']},build:{outDir:'dist',emptyOutDir:true,sourcemap:false}});
