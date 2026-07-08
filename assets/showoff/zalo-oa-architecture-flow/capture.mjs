// Portable section-capture for this showcase.
// Reuses the FRONTEND Playwright install + system Chrome (the show-off skill's
// bundled puppeteer is not installed locally). Run from anywhere:
//   node capture.mjs --settle-delay 2000
import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Resolve playwright from the project frontend so this script is location-independent.
const require = createRequire('/Users/dev/Documents/projects/vfic-ats/ChatBot/frontend/package.json');
const { chromium } = require('playwright');

const VIEWPORTS = {
  horizontal: { width: 1920, height: 1080 },
  vertical:   { width: 1080, height: 1920 },
  square:     { width: 1080, height: 1080 },
};

function parseArgs(argv){
  const a={};
  for(let i=0;i<argv.length;i++){
    const t=argv[i]; if(!t.startsWith('--')) continue;
    const k=t.slice(2); const n=argv[i+1];
    if(n && !n.startsWith('--')){ a[k]=n; i++; } else a[k]=true;
  }
  return a;
}
async function ready(page, settle){
  await page.evaluate(async ()=>{
    const wt=(p,ms)=>Promise.race([p,new Promise(r=>setTimeout(r,ms))]);
    if(document.fonts?.ready) await wt(document.fonts.ready, 12000);
    await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
  });
  if(settle>0) await page.waitForTimeout(settle);
}

const args=parseArgs(process.argv.slice(2));
const root = __dirname;
const url = args.url || `file://${path.join(root,'index.html')}`;
const out = args['output-dir'] || path.join(root,'images');
const sections = (args.sections || '#hero,#recruiter-frontend,#backend-brain,#zalo-oa-bridge,#webhook-conduit,#e2e-flow').split(',').map(s=>s.trim()).filter(Boolean);
const ratios = (args.ratios || 'horizontal,vertical,square').split(',').map(s=>s.trim());
const settle = parseInt(args['settle-delay'] || '2000', 10);

await fs.promises.mkdir(out, { recursive:true });
const browser = await chromium.launch({ channel:'chrome', headless:true,
  args:['--no-sandbox','--disable-setuid-sandbox','--disable-dev-shm-usage'] });

const errors=[], results=[];
await Promise.all(ratios.map(async (ratio)=>{
  const vp=VIEWPORTS[ratio]; if(!vp){ errors.push({ratio,error:'unknown ratio'}); return; }
  const page=await browser.newPage({ viewport:{width:vp.width,height:vp.height}, deviceScaleFactor:2 });
  await page.goto(url,{ waitUntil:'networkidle', timeout:30000 });
  await ready(page, settle);
  for(const sel of sections){
    try{
      const el=await page.$(sel);
      if(!el){ errors.push({section:sel,ratio,error:'not found'}); continue; }
      await el.scrollIntoViewIfNeeded();
      await ready(page, Math.min(settle,500));
      const name=sel.replace(/^[#.]/,'').replace(/[^a-zA-Z0-9-_]/g,'_');
      const fp=path.join(out, `${ratio}-${name}.png`);
      await el.screenshot({ path:fp });
      results.push({section:sel,ratio,file:fp});
    }catch(e){ errors.push({section:sel,ratio,error:e.message}); }
  }
  await page.close();
}));
await browser.close();
console.log(JSON.stringify({success:errors.length===0, captured:results.length, errors}, null, 2));
process.exit(errors.length?1:0);
