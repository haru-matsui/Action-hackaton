import test from 'node:test';
import assert from 'node:assert/strict';
import {WorkspaceNavigation} from '../backend/static/js/workspace.js';
import {SandboxSession} from '../backend/static/js/sandbox.js';

function element(dataset = {}) {
  const classes = new Set(), attributes = new Map([['role','tab']]);
  return {dataset, hidden:false, tabIndex:0,
    classList:{contains:key => classes.has(key), toggle:(key, active) => active ? classes.add(key) : classes.delete(key)},
    getAttribute:key => attributes.get(key), setAttribute:(key,value) => attributes.set(key,value),
    removeAttribute:key => attributes.delete(key)};
}
function fixture(beforeChange) {
  const panels = ['timeline','table','graph'].map(view => element({viewPanel:view}));
  const tabs = ['timeline','table','graph'].map(view => element({view}));
  const nodes = Object.fromEntries(['#assistantPanel','.workspace-grid','#btnAssistant'].map(key => [key,element()]));
  const root = {querySelector:key => nodes[key], querySelectorAll:key => key === '[data-view-panel]' ? panels : tabs};
  const nav = new WorkspaceNavigation(root, {beforeChange});
  return {nav,panels,tabs,nodes};
}

test('leaving timeline closes sandbox and rejects its late result', async () => {
  let resolveCalculation;
  const session = new SandboxSession(() => new Promise(resolve => { resolveCalculation = resolve; }), () => {});
  session.enter('p','r');
  const calculation = session.shift('a',3);
  const {nav,panels,tabs} = fixture(async view => {
    if (view !== 'timeline') session.leave();
    return true;
  });
  assert.equal(await nav.select('table'),true);
  assert.equal(session.active,false);
  resolveCalculation({scenario_key:'late'}); await calculation;
  assert.equal(session.data,null);
  assert.deepEqual(panels.map(p => p.hidden),[true,false,true]);
  assert.deepEqual(tabs.map(p => p.tabIndex),[-1,0,-1]);
  assert.equal(tabs[1].getAttribute('aria-selected'),'true');
  await nav.select('graph');
  assert.deepEqual(panels.map(p => p.hidden),[true,true,false]);
});

test('cancelled discard keeps view and repeated clicks cannot open multiple confirmations', async () => {
  let finish, calls = 0;
  const {nav} = fixture(() => { calls++; return new Promise(resolve => { finish = resolve; }); });
  const first = nav.select('table');
  assert.equal(await nav.select('graph'),false); assert.equal(calls,1);
  finish(false); assert.equal(await first,false); assert.equal(nav.view,'timeline');
});

test('collapsing the assistant returns the entire grid to the project and can be reversed', () => {
  const {nav,nodes} = fixture();
  nav.assistant(false);
  assert.equal(nodes['#assistantPanel'].hidden,true);
  assert.equal(nodes['.workspace-grid'].classList.contains('assistant-collapsed'),true);
  assert.equal(nodes['#btnAssistant'].getAttribute('aria-expanded'),'false');
  nav.assistant(true);
  assert.equal(nodes['#assistantPanel'].hidden,false);
  assert.equal(nodes['.workspace-grid'].classList.contains('assistant-collapsed'),false);
  assert.equal(nodes['#btnAssistant'].getAttribute('aria-expanded'),'true');
});
