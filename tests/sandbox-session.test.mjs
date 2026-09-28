import test from 'node:test';
import assert from 'node:assert/strict';
import {SandboxSession} from '../backend/static/js/sandbox.js';

const tick = () => new Promise(resolve => setImmediate(resolve));
const result = (key = 'scenario', extra = {}) => ({scenario_key:key, explanation:'Расчёт', llm:false, ai:{source:'pending'}, ...extra});
function harness() {
  const calls = [], timers = new Map(); let id = 0;
  const send = (pid, path, body, signal) => new Promise((resolve, reject) => calls.push({pid,path,body,signal,resolve,reject}));
  const session = new SandboxSession(send, () => {}, {
    schedule:fn => { timers.set(++id, fn); return id; }, cancel:key => timers.delete(key),
  });
  session.enter('project', 'revision');
  return {session,calls,timers,fire:() => { const batch = [...timers.values()]; timers.clear(); batch.forEach(fn => fn()); }};
}

test('default timers retain the browser global receiver during startup, scheduling and reset', async t => {
  const timers = new Map(); let id = 0;
  t.mock.method(globalThis, 'setTimeout', function (callback) {
    if (this !== globalThis) throw new TypeError('Illegal invocation');
    timers.set(++id, callback); return id;
  });
  t.mock.method(globalThis, 'clearTimeout', function (timer) {
    if (this !== globalThis) throw new TypeError('Illegal invocation');
    timers.delete(timer);
  });
  const session = new SandboxSession(async () => result(), () => {});
  // Opening a project first clears the inactive sandbox.
  assert.doesNotThrow(() => session.leave());
  session.enter('project', 'revision');
  await session.shift('a', 1);
  assert.equal(session.phase, 'ready'); assert.equal(timers.size, 1);
  session.pause(); assert.equal(timers.size, 0);
  session.resume(); assert.equal(timers.size, 1);
  session.reset(); assert.equal(timers.size, 0);
  assert.equal(session.phase, 'idle');
});

test('rapid keys accumulate before calculation returns and stale calculations are ignored', async () => {
  const {session:s,calls,timers} = harness();
  const first = s.shift('a',1), second = s.shift('a',1);
  assert.equal(calls[1].body.shifts.a,2);
  assert.equal(calls[0].signal.aborted,true);
  calls[1].resolve(result('new')); await second;
  calls[0].resolve(result('old')); await first;
  assert.equal(s.data.scenario_key,'new'); assert.equal(timers.size,1);
  assert.equal(s.canApply,true);
});

test('AI waits for pause and only the latest scenario is explained', async () => {
  const {session:s,calls,fire,timers} = harness();
  let work = s.shift('a',3); calls[0].resolve(result('a')); await work;
  assert.equal(calls.length,1); assert.equal(s.aiPhase,'waiting');
  s.pause(); assert.equal(timers.size,0);
  work = s.shift('b',2); calls[1].resolve(result('ab')); await work;
  fire(); assert.equal(calls.length,3);
  assert.deepEqual(calls[2].body.shifts,{a:3,b:2}); assert.equal(calls[2].body.explain,true);
  calls[2].resolve(result('ab',{llm:true,explanation:'Актуальный ответ'})); await tick();
  assert.equal(s.aiPhase,'ready'); assert.equal(s.data.explanation,'Актуальный ответ');
});

test('reset, project switch and exit discard late AI replies', async () => {
  for (const action of [s => s.reset(), s => s.enter('other','other-revision'), s => s.leave()]) {
    const {session:s,calls,fire} = harness();
    const work = s.shift('a',1); calls[0].resolve(result()); await work;
    fire(); action(s);
    calls[1].resolve(result('scenario',{llm:true,explanation:'Устаревший ответ'})); await tick();
    assert.equal(s.data,null); assert.equal(s.dirty,false); assert.equal(calls[1].signal.aborted,true);
  }
});

test('applying does not wait for AI, cancels it and prevents duplicate writes or edits', async () => {
  const {session:s,calls,fire} = harness();
  const work = s.shift('a',3); calls[0].resolve(result()); await work; fire();
  const applying = s.apply();
  assert.equal(calls[2].path,'/sandbox/apply'); assert.equal(calls[1].signal.aborted,true);
  assert.equal(s.canApply,false); assert.equal(await s.apply(),null);
  s.shift('a',1); s.reset(); assert.deepEqual(s.shifts,{a:3});
  calls[1].resolve(result('scenario',{llm:true,explanation:'Поздний ответ'})); await tick();
  assert.notEqual(s.data.explanation,'Поздний ответ');
  calls[2].resolve({applied:true}); assert.equal((await applying).applied,true);
});

test('AI failure preserves calculated data and apply remains available; revision conflict blocks it', async () => {
  const {session:s,calls,fire} = harness();
  const work = s.shift('a',2); calls[0].resolve(result()); await work; fire();
  calls[1].reject(new Error('offline')); await tick();
  assert.equal(s.aiPhase,'error'); assert.equal(s.canApply,true);
  const retry = s.retryExplanation(); calls[2].reject(Object.assign(new Error('changed'),{code:'revision_conflict'})); await retry;
  assert.equal(s.phase,'conflict'); assert.equal(s.canApply,false);
});

test('return to baseline sends no requests and an earlier start respects the original delay', async () => {
  const {session:s,calls} = harness();
  const work = s.shift('a',-9,-3); assert.equal(calls[0].body.shifts.a,-3);
  calls[0].resolve(result()); await work;
  await s.shift('a',3,-3); assert.deepEqual(s.shifts,{}); assert.equal(s.data,null);
  assert.equal(calls.length,1); assert.equal(s.canApply,false);
});

test('lost apply response requires reload and cannot accidentally apply the same shift twice', async () => {
  const {session:s,calls} = harness();
  const work = s.shift('a',2); calls[0].resolve(result()); await work;
  const applying = s.apply(); calls[1].reject(new Error('connection lost')); await applying;
  assert.equal(s.phase,'conflict'); assert.equal(s.canApply,false); assert.equal(await s.apply(),null);
  assert.equal(calls.length,2);
});

test('click without movement and cancelled drag keep the current explanation without another request', async () => {
  const {session:s,calls,fire} = harness();
  s.pause(); await s.shift('a',0); assert.equal(calls.length,0); assert.equal(s.phase,'idle');
  const work = s.shift('a',2); calls[0].resolve(result()); await work; fire();
  calls[1].resolve(result('scenario',{llm:true,explanation:'Ответ для текущего сценария'})); await tick();
  s.pause(); s.resume();
  assert.equal(s.phase,'ready'); assert.equal(s.aiPhase,'ready'); assert.equal(calls.length,2);
  assert.equal(s.data.explanation,'Ответ для текущего сценария');
});
