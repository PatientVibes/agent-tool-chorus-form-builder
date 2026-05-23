// All 4 rule kinds on the canonical example (STAT + MEMO + ACCT + BATC).

const customRules = `
(function(awdForm) {
  function applyAll() {
    var stat = awdForm.getValue("STAT");

    // MEMO visible_when STAT == "R"
    awdForm[(stat === "R") ? "show" : "hide"]("MEMO");

    // MEMO required_when STAT == "R"
    awdForm.setRequired("MEMO", stat === "R");

    // ACCT enabled_when STAT in ["A", "P"]
    awdForm[((stat === "A") || (stat === "P")) ? "enable" : "disable"]("ACCT");

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
    const host = makeHost();
    host.state['STAT'] = 'A';
    host.state['BATC'] = '';
    const awdForm = loadShim(host);
    loadAndRunCustomRules(awdForm, customRules);

    awdForm._emit('form-open');

    const mutators = host.calls.filter(c => c.method !== 'getValue' && c.method !== 'isEmpty');
    const seq = mutators.map(c => `${c.method}(${c.args.map(JSON.stringify).join(',')})`);

    return {
      assertions: [
        {
          name: 'STAT=A + empty BATC fires hide(MEMO), setRequired(MEMO,false), enable(ACCT), setValue(BATC,BATCH-AUTO) — in declared order',
          ok: seq.join(' | ') === 'hide("MEMO") | setRequired("MEMO",false) | enable("ACCT") | setValue("BATC","BATCH-AUTO")',
          detail: seq.join(' | '),
        },
      ],
    };
  },
};
