/* awdForm.js v0.1.0 — chorus-form-builder mini-runtime shim
 *
 * Public API used by generated customRules JS:
 *   awdForm.getValue(code)
 *   awdForm.isEmpty(code)
 *   awdForm.show(code)
 *   awdForm.hide(code)
 *   awdForm.enable(code)
 *   awdForm.disable(code)
 *   awdForm.setRequired(code, b)
 *   awdForm.setValue(code, v)         -- does NOT fire field-change
 *   awdForm.on(eventName, fn)         -- 'form-open' or 'field-change:CODE'
 *   awdForm._emit(eventName)          -- TEST-ONLY: synthetic event trigger
 *
 * In v0.1, every state-mutator delegates to window.__awdFormHost (the test
 * runner or future Chorus bridge supplies that host). The bridge to the
 * real Chorus runtime is the C v0.2 milestone; the contract above is what
 * the bridge must satisfy.
 */
(function (root) {
  var host = (root && root.__awdFormHost) || {};
  var listeners = {};  // eventName -> [fn, fn, ...]

  function _call(method, args) {
    if (typeof host[method] === 'function') {
      return host[method].apply(host, args);
    }
    // No host method bound (e.g., stub environment). Silently no-op for
    // mutators; for getters, return undefined.
    return undefined;
  }

  var api = {
    // --- accessors ---
    getValue: function (code) { return _call('getValue', [code]); },
    isEmpty:  function (code) { return _call('isEmpty',  [code]); },

    // --- mutators ---
    show:        function (code)    { _call('show',        [code]); },
    hide:        function (code)    { _call('hide',        [code]); },
    enable:      function (code)    { _call('enable',      [code]); },
    disable:     function (code)    { _call('disable',     [code]); },
    setRequired: function (code, b) { _call('setRequired', [code, b]); },
    setValue:    function (code, v) { _call('setValue',    [code, v]); },
    //                                          ^^^^^^^^
    //   Intentionally does NOT also emit a field-change event. Sub-project
    //   C v0.1 forbids cascading rules; the codegen and the host contract
    //   both rely on this no-cascade guarantee.

    // --- events ---
    on: function (eventName, fn) {
      if (!listeners[eventName]) listeners[eventName] = [];
      listeners[eventName].push(fn);
    },

    // --- test-only ---
    _emit: function (eventName) {
      var fns = listeners[eventName] || [];
      for (var i = 0; i < fns.length; i++) {
        fns[i]();
      }
    },
  };

  root.awdForm = api;
})(typeof window !== 'undefined' ? window : this);
