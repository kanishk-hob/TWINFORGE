import {build, context} from 'esbuild';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const base=process.env.TWINFORGE_API_BASE || '';
if(base && (!base.startsWith('/') || base.startsWith('//') || /[?#]/.test(base))) throw Error('API base must be an empty or same-origin path prefix');
const options={entryPoints:[root+'app/static/dashboard/console.js'],outfile:root+'app/static/dashboard/build/console.js',bundle:true,minify:true,format:'esm',target:'es2022',nodePaths:[root+'frontend/node_modules'],define:{__API_BASE__:JSON.stringify(base.replace(/\/$/,''))},logLevel:'info'};
if(process.argv.includes('--watch')) await (await context(options)).watch(); else await build(options);
