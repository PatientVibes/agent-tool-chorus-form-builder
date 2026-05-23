// __awdFormHost stub that records every mutator call made by the shim.
// Tests inspect host.calls to verify the shim translated event -> method
// dispatch correctly. State lives in host.state so tests can prime values.

function makeHost() {
  return {
    state: {},     // field code -> current value
    calls: [],     // append-only list of {method, args}

    getValue(code) {
      this.calls.push({method: 'getValue', args: [code]});
      return this.state[code];
    },
    isEmpty(code) {
      const v = this.state[code];
      const empty = v === '' || v === null || v === undefined;
      this.calls.push({method: 'isEmpty', args: [code], result: empty});
      return empty;
    },
    show(code)             { this.calls.push({method: 'show',        args: [code]}); },
    hide(code)             { this.calls.push({method: 'hide',        args: [code]}); },
    enable(code)           { this.calls.push({method: 'enable',      args: [code]}); },
    disable(code)          { this.calls.push({method: 'disable',     args: [code]}); },
    setRequired(code, b)   { this.calls.push({method: 'setRequired', args: [code, b]}); },
    setValue(code, v) {
      this.calls.push({method: 'setValue', args: [code, v]});
      this.state[code] = v;  // mirror real runtime; but does NOT fire change event
    },
  };
}

module.exports = { makeHost };
