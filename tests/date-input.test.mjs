import test from 'node:test';
import assert from 'node:assert/strict';
import {parseDateInput, dateRange, bindDateField, setDateField, calendarMonth} from '../backend/static/js/date-input.js';

test('typed, compact and pasted dates normalize unambiguously; invalid dates are rejected', () => {
  for (const value of ['28.09.2026','28092026','2026-09-28',' 28.9.2026 ']) {
    assert.deepEqual(parseDateInput(value),{iso:'2026-09-28',error:''});
  }
  assert.equal(parseDateInput('29.02.2024').error,'');
  for (const value of ['29.02.2026','31.04.2026','00.12.2026','28.13.2026','28.09.26','28.09.0002','28.09.2101']) {
    assert.ok(parseDateInput(value).error,value);
  }
  assert.ok(parseDateInput('',true).error);
  assert.equal(parseDateInput('').iso,null);
});

test('start must be today or later; existing historical date may be retained without blocking deadline edits', () => {
  const rules = {today:'2026-09-28',existingStart:'2026-09-22'};
  assert.equal(dateRange('22.09.2026','22.10.2026',rules).valid,true);
  assert.equal(dateRange('23.09.2026','22.10.2026',rules).valid,false);
  assert.equal(dateRange('22.09.2026','22.10.2026',{today:rules.today}).valid,false);
  assert.equal(dateRange('28.09.2026','22.10.2026',rules).valid,true);
  assert.equal(dateRange('29.09.2026','28.09.2026',rules).valid,false);
  assert.equal(dateRange('29.09.2026','',rules).valid,true);
});

function control(value='') {
  return {value,listeners:{},required:false,selectionStart:0,focus(){},setCustomValidity(error){this.error=error;},
    addEventListener(event,listener){this.listeners[event]=listener;}};
}

test('typing and deletion do not rewrite text or move the caret; blur and calendar selection synchronize', () => {
  const input = control(), picker = control(), button = control();
  let changes = 0;
  bindDateField(input,picker,button,()=>{changes++;});
  for (const value of ['2','28','28.','28.0','28.09.','28.09.2026','28.09.202','28.09.20','']) {
    input.value = value; input.selectionStart = Math.min(3,value.length);
    const cursor = input.selectionStart;
    input.listeners.input();
    assert.equal(input.value,value); assert.equal(input.selectionStart,cursor);
  }
  input.value = '28092026'; input.listeners.blur();
  assert.equal(input.value,'28.09.2026'); assert.equal(picker.value,'2026-09-28');
  picker.value = '2026-10-05'; picker.listeners.change();
  assert.equal(input.value,'05.10.2026');
  setDateField(input,picker,null); assert.equal(input.value,''); assert.equal(picker.value,'');
  assert.ok(changes > 0);
});


test('picker displays weekday alignment, leap days and year boundaries correctly', () => {
  const leap = calendarMonth(2024,1);
  assert.equal(leap.days.length,29);
  assert.equal(leap.padding,3);
  assert.equal(leap.days.at(-1).iso,'2024-02-29');
  assert.equal(calendarMonth(2026,1).days.length,28);
  assert.equal(calendarMonth(2026,12).days[0].iso,'2027-01-01');
  assert.equal(calendarMonth(2026,-1).days.at(-1).iso,'2025-12-31');
});
