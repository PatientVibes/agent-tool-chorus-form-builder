// One enabled_when rule with membership condition.

const customRules = `
(function(awdForm) {
  function applyAll() {
    var stat = awdForm.getValue("STAT");

    // ACCT enabled_when STAT in ["A", "P"]
    awdForm[((stat === "A") || (stat === "P")) ? "enable" : "disable"]("ACCT");

  }

  awdForm.on("form-open", applyAll);
  awdForm.on("field-change:STAT", applyAll);
})(window.awdForm);
`;

module.exports = {
  run({makeHost, loadShim, loadAndRunCustomRules}) {
    const host = makeHost();
    const awdForm = loadShim(host);
    loadAndRunCustomRules(awdForm, customRules);

    const a = [];

    // STAT='A' -> enable ACCT
    host.state['STAT'] = 'A';
    awdForm._emit('form-open');
    a.push({
      name: 'STAT=A -> enable ACCT',
      ok: host.calls[host.calls.length - 1].method === 'enable',
      detail: JSON.stringify(host.calls[host.calls.length - 1]),
    });

    // STAT='P' (also in set) -> enable
    host.state['STAT'] = 'P';
    awdForm._emit('field-change:STAT');
    a.push({
      name: 'STAT=P -> enable ACCT',
      ok: host.calls[host.calls.length - 1].method === 'enable',
    });

    // STAT='R' (not in set) -> disable
    host.state['STAT'] = 'R';
    awdForm._emit('field-change:STAT');
    a.push({
      name: 'STAT=R -> disable ACCT',
      ok: host.calls[host.calls.length - 1].method === 'disable',
    });

    return {assertions: a};
  },
};
