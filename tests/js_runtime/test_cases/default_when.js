// default_when: set BATC to 'BATCH-AUTO' iff STAT == 'A' and BATC is empty.

const customRules = `
(function(awdForm) {
  function applyAll() {
    var stat = awdForm.getValue("STAT");

    // BATC default_when STAT == "A" (default_value "BATCH-AUTO", set-if-empty)
    if ((stat === "A") && awdForm.isEmpty("BATC")) {
      awdForm.setValue("BATC", "BATCH-AUTO");
    }

  }

  awdForm.on("form-open", applyAll);
  awdForm.on("field-change:STAT", applyAll);
})(window.awdForm);
`;

module.exports = {
  run({makeHost, loadShim, loadAndRunCustomRules}) {
    const a = [];

    // Case A: STAT=A, BATC empty -> setValue should fire
    {
      const host = makeHost();
      host.state['STAT'] = 'A';
      host.state['BATC'] = '';
      const awdForm = loadShim(host);
      loadAndRunCustomRules(awdForm, customRules);
      awdForm._emit('form-open');
      const set = host.calls.filter(c => c.method === 'setValue');
      a.push({
        name: 'STAT=A + empty BATC -> setValue("BATC", "BATCH-AUTO")',
        ok: set.length === 1 && set[0].args[0] === 'BATC' && set[0].args[1] === 'BATCH-AUTO',
        detail: JSON.stringify(set),
      });
    }

    // Case B: STAT=A, BATC already 'USER-VALUE' -> no setValue
    {
      const host = makeHost();
      host.state['STAT'] = 'A';
      host.state['BATC'] = 'USER-VALUE';
      const awdForm = loadShim(host);
      loadAndRunCustomRules(awdForm, customRules);
      awdForm._emit('form-open');
      const set = host.calls.filter(c => c.method === 'setValue');
      a.push({
        name: 'STAT=A + non-empty BATC -> no setValue (set-if-empty)',
        ok: set.length === 0,
        detail: JSON.stringify(set),
      });
    }

    // Case C: STAT='R' -> no setValue regardless of BATC
    {
      const host = makeHost();
      host.state['STAT'] = 'R';
      host.state['BATC'] = '';
      const awdForm = loadShim(host);
      loadAndRunCustomRules(awdForm, customRules);
      awdForm._emit('form-open');
      const set = host.calls.filter(c => c.method === 'setValue');
      a.push({
        name: 'STAT=R + empty BATC -> no setValue (condition false)',
        ok: set.length === 0,
      });
    }

    return {assertions: a};
  },
};
