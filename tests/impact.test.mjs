import test from 'node:test';
import assert from 'node:assert/strict';
import {ImpactExplanation} from '../backend/static/js/impact.js';

const result = {explanation_id:'receipt', result_revision:'revision', explanation:'calculated'};
function fixture() {
  const requests = [], shown = [], errors = [];
  const session = new ImpactExplanation((pid, body, signal) => new Promise((resolve, reject) => requests.push({pid, body, signal, resolve, reject})));
  return {requests, shown, errors, session,
    run:(current = () => true) => session.run('p', result, current, r => shown.push(r), e => errors.push(e))};
}
test('explanation preserves calculation and uses its server receipt', async () => {
  const f = fixture(), pending = f.run();
  assert.deepEqual(f.requests[0].body, {explanation_id:'receipt'});
  f.requests[0].resolve({...result, explanation:'AI', llm:true}); await pending;
  assert.equal(f.shown[0].explanation, 'AI');
});
test('new preview discards old response even if transport ignores abort', async () => {
  const f = fixture(), old = f.run(), fresh = f.run();
  assert.ok(f.requests[0].signal.aborted);
  f.requests[1].resolve({...result, explanation:'latest'}); await fresh;
  f.requests[0].resolve({...result, explanation:'stale'}); await old;
  assert.deepEqual(f.shown.map(r => r.explanation), ['latest']);
});
test('closing or editing cancels pending explanations and errors', async () => {
  const f = fixture(), pending = f.run(); f.session.cancel();
  f.requests[0].reject(new Error('late error')); await pending;
  assert.equal(f.errors.length, 0); assert.equal(f.shown.length, 0);
});
test('project version and receipt must still match', async () => {
  for (const mismatch of ['context','revision','receipt']) {
    const f = fixture(), pending = f.run(() => mismatch !== 'context');
    f.requests[0].resolve({...result,
      ...(mismatch === 'revision' ? {result_revision:'other'} : {}),
      ...(mismatch === 'receipt' ? {explanation_id:'other'} : {})});
    await pending; assert.equal(f.shown.length, 0);
  }
});
test('current failure can display calculated fallback', async () => {
  const f = fixture(), pending = f.run();
  f.requests[0].reject(new Error('offline')); await pending;
  assert.equal(f.errors.length, 1); assert.equal(f.shown.length, 0);
});
