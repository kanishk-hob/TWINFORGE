import {readdir,readFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
const dir=new URL('../app/static/dashboard/',import.meta.url);
for(const name of (await readdir(dir)).filter(n=>n.endsWith('.js'))) {
  const path=new URL(name,dir); execFileSync(process.execPath,['--check',path.pathname.replace(/^\/(\w:)/,'$1')]);
  const text=await readFile(path,'utf8');
  if(/innerHTML|insertAdjacentHTML|localhost:8000|127\.0\.0\.1:8000/.test(text)) throw Error('Unsafe rendering or source URL in '+name);
}
console.log('JavaScript syntax and rendering-safety checks passed');
