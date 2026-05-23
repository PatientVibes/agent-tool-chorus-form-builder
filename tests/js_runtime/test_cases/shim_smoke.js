// Layer-C smoke test for the awdForm shim — verifies the shim's public
// methods dispatch correctly to __awdFormHost and that on(eventName, fn)
// registers callbacks that fire on awdForm._emit().

module.exports = {
  run({makeHost, loadShim}) {
    const host = makeHost();
    host.state['STAT'] = 'R';
    const awdForm = loadShim(host);

    const assertions = [];

    // 1. getValue delegates to host and returns the host's stored value.
    const got = awdForm.getValue('STAT');
    assertions.push({
      name: 'getValue delegates to host',
      ok: got === 'R',
      detail: `expected 'R' got ${JSON.stringify(got)}`,
    });

    // 2. show / hide / enable / disable / setRequired / setValue
    awdForm.show('MEMO');
    awdForm.hide('ACCT');
    awdForm.enable('BATC');
    awdForm.disable('AMTV');
    awdForm.setRequired('MEMO', true);
    awdForm.setValue('BATC', 'BATCH-AUTO');

    // Whitelist the methods we care about (more robust than blacklisting
    // getValue — if another accessor were added to host_recorder it could
    // accidentally appear in this sequence and break the assertion).
    const mutatorMethods = new Set(['show', 'hide', 'enable', 'disable', 'setRequired', 'setValue']);
    const methodSeq = host.calls.filter(c => mutatorMethods.has(c.method)).map(c => c.method);
    assertions.push({
      name: 'mutator methods reach host in declared order',
      ok: methodSeq.join(',') === 'show,hide,enable,disable,setRequired,setValue',
      detail: 'got: ' + methodSeq.join(','),
    });

    // 3. isEmpty
    host.state['EMPTY'] = '';
    host.state['FILLED'] = 'x';
    assertions.push({
      name: 'isEmpty true for empty string',
      ok: awdForm.isEmpty('EMPTY') === true,
    });
    assertions.push({
      name: 'isEmpty false for non-empty',
      ok: awdForm.isEmpty('FILLED') === false,
    });

    // 4. on(eventName, fn) + emit. The shim must expose an internal _emit
    // so the runner can drive synthetic events. v0.1 design exposes:
    //   awdForm.on('form-open', fn)
    //   awdForm.on('field-change:STAT', fn)
    //   awdForm._emit(eventName)   <-- test-only escape hatch
    let openCount = 0;
    let changeCount = 0;
    awdForm.on('form-open', () => { openCount++; });
    awdForm.on('field-change:STAT', () => { changeCount++; });
    awdForm._emit('form-open');
    awdForm._emit('form-open');
    awdForm._emit('field-change:STAT');

    assertions.push({
      name: 'form-open callbacks fire on _emit',
      ok: openCount === 2,
      detail: `openCount=${openCount}`,
    });
    assertions.push({
      name: 'field-change:CODE callbacks fire on _emit',
      ok: changeCount === 1,
      detail: `changeCount=${changeCount}`,
    });

    // 5. setValue does NOT fire field-change (sub-project C v0.1 contract)
    let cascadeCount = 0;
    awdForm.on('field-change:BATC', () => { cascadeCount++; });
    awdForm.setValue('BATC', 'XYZ');
    assertions.push({
      name: 'setValue does NOT fire field-change (no-cascade contract)',
      ok: cascadeCount === 0,
      detail: `cascadeCount=${cascadeCount}`,
    });

    return {assertions};
  },
};
