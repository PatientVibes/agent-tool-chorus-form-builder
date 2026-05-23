// Drive a customRules JS that has one visible_when rule. Verify show/hide
// fires on form-open and on field-change with the correct boolean.

const customRules = `
(function(awdForm) {
  function applyAll() {
    var stat = awdForm.getValue("STAT");

    // MEMO visible_when STAT == "R"
    awdForm[(stat === "R") ? "show" : "hide"]("MEMO");

  }

  awdForm.on("form-open", applyAll);
  awdForm.on("field-change:STAT", applyAll);
})(window.awdForm);
`;

module.exports = {
  run({makeHost, loadShim, loadAndRunCustomRules}) {
    const host = makeHost();
    host.state['STAT'] = 'A';  // initial: not Rejected -> MEMO should be hidden
    const awdForm = loadShim(host);
    loadAndRunCustomRules(awdForm, customRules);

    const a = [];

    // form-open with STAT='A' -> hide MEMO
    awdForm._emit('form-open');
    const lastCall1 = host.calls[host.calls.length - 1];
    a.push({
      name: 'form-open with STAT=A hides MEMO',
      ok: lastCall1.method === 'hide' && lastCall1.args[0] === 'MEMO',
      detail: JSON.stringify(lastCall1),
    });

    // Change STAT to 'R' and re-emit -> show MEMO
    host.state['STAT'] = 'R';
    awdForm._emit('field-change:STAT');
    const lastCall2 = host.calls[host.calls.length - 1];
    a.push({
      name: 'field-change:STAT with STAT=R shows MEMO',
      ok: lastCall2.method === 'show' && lastCall2.args[0] === 'MEMO',
      detail: JSON.stringify(lastCall2),
    });

    return {assertions: a};
  },
};
