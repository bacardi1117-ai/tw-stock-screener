import fs from 'node:fs';
import {qgmScores,evaluateAll} from '../docs/engine.mjs';
const config=JSON.parse(fs.readFileSync(new URL('../config/strategies.json',import.meta.url),'utf8'));
const rows=JSON.parse(fs.readFileSync(new URL('./strategy_fixture.json',import.meta.url),'utf8'));
process.stdout.write(JSON.stringify(rows.map(row=>({...qgmScores(row,config),...evaluateAll(row,config)}))));
