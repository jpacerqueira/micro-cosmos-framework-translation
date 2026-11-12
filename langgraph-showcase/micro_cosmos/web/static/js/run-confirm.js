(function () {
  function askLlmConfirm(form) {
    const panel = form.querySelector(".llm-confirm-inline");
    if (!panel) return Promise.resolve(true);
    const submitBtn = form.querySelector('button[type="submit"]');
    const confirmBtn = panel.querySelector('[data-modal-action="confirm"]');
    const cancelBtn = panel.querySelector('[data-modal-action="cancel"]');

    return new Promise((resolve) => {
      panel.hidden = false;
      if (submitBtn) submitBtn.hidden = true;
      confirmBtn.focus();

      function cleanup(result) {
        panel.hidden = true;
        if (submitBtn) submitBtn.hidden = false;
        confirmBtn.removeEventListener("click", onConfirm);
        cancelBtn.removeEventListener("click", onCancel);
        resolve(result);
      }
      function onConfirm() { cleanup(true); }
      function onCancel() { cleanup(false); }

      confirmBtn.addEventListener("click", onConfirm);
      cancelBtn.addEventListener("click", onCancel);
    });
  }

  // Listener is on `document`, not `document.body` — this script tag loads in
  // <head>, before <body> exists, so `document.body` would still be null here.
  document.addEventListener("htmx:confirm", function (evt) {
    const form = evt.target.closest("form");
    const skipLlmInput = form && form.querySelector('input[name="skip_llm"]');
    if (!skipLlmInput || skipLlmInput.checked) return;

    evt.preventDefault();
    askLlmConfirm(form).then((proceed) => {
      if (proceed) evt.detail.issueRequest(true);
    });
  });
})();
