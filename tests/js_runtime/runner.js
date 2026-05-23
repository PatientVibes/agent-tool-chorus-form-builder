// Generic Node runner for shim integration tests.
//
// Usage: node runner.js <test-case-file>
//
// The test-case file must export a single function `run({makeHost, loadShim})
// -> {assertions: [{name, ok, detail?}, ...]}`.
// Runner prints one JSON line `{name, ok, detail?}` per assertion and exits 0
// iff every assertion passed.

const path = require('path');
const fs = require('fs');
const vm = require('vm');

const {makeHost} = require('./host_recorder');

function loadShim(host) {
  // Load src/chorus_form_builder/runtime/awdForm.js into a fresh context
  // where window.__awdFormHost = host. Returns the populated context's
  // window.awdForm.
  const shimPath = path.resolve(
    __dirname,
    '..',
    '..',
    'src',
    'chorus_form_builder',
    'runtime',
    'awdForm.js'
  );
  const shimSrc = fs.readFileSync(shimPath, 'utf8');
  const ctx = vm.createContext({
    window: {__awdFormHost: host},
  });
  vm.runInContext(shimSrc, ctx);
  return ctx.window.awdForm;
}

function loadAndRunCustomRules(awdForm, customRulesSrc) {
  // Drop the customRules body into a fresh sub-context that sees `window`
  // as a thin shim binding window.awdForm to the loaded shim.
  const ctx = vm.createContext({window: {awdForm}});
  vm.runInContext(customRulesSrc, ctx);
}

const tcPath = process.argv[2];
if (!tcPath) {
  console.error('usage: node runner.js <test-case-file>');
  process.exit(2);
}

const tc = require(path.resolve(tcPath));
const result = tc.run({makeHost, loadShim, loadAndRunCustomRules});

let allOk = true;
for (const a of result.assertions) {
  console.log(JSON.stringify(a));
  if (!a.ok) allOk = false;
}
process.exit(allOk ? 0 : 1);
