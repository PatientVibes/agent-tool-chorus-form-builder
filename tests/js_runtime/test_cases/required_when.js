// One required_when rule — verifies setRequired(field, bool) fires with
// the right boolean both on form-open and on field-change.

const customRules = `
(function(awdForm) {
  function applyAll() {
    var stat = awdForm.getValue("STAT");

    // MEMO required_when STAT == "R"
    awdForm.setRequired("MEMO", stat === "R");

  }

  awdForm.on("form-open", applyAll);
  awdForm.on("field-change:STAT", applyAll);
})(window.awdForm);
`;

module.exports = {
  run({makeHost, loadShim, loadAndRunCustomRules}) {
    const host = makeHost();
    host.state['STAT'] = 'R';
    const awdForm = loadShim(host);
    loadAndRunCustomRules(awdForm, customRules);

    awdForm._emit('form-open');
    const c1 = host.calls[host.calls.length - 1];

    host.state['STAT'] = 'A';
    awdForm._emit('field-change:STAT');
    const c2 = host.calls[host.calls.length - 1];

    return {
      assertions: [
        {name: 'STAT=R -> setRequired(MEMO, true)',
         ok: c1.method === 'setRequired' && c1.args[1] === true,
         detail: JSON.stringify(c1)},
        {name: 'STAT=A -> setRequired(MEMO, false)',
         ok: c2.method === 'setRequired' && c2.args[1] === false,
         detail: JSON.stringify(c2)},
      ],
    };
  },
};
