async function notImplemented(name, payload) {
  throw new Error(
    `${name} is not implemented. Replace browser-provider.example.js with your actual sandbox browser adapter. Payload: ${JSON.stringify(
      payload || {}
    )}`
  );
}

module.exports = {
  browserProvider: {
    navigate({ url }) {
      return notImplemented('navigate', { url });
    },
    click({ target }) {
      return notImplemented('click', { target });
    },
    type({ target, text, clearFirst, pressEnter }) {
      return notImplemented('type', { target, text, clearFirst, pressEnter });
    },
    submit({ target }) {
      return notImplemented('submit', { target });
    },
    openTab({ url, label }) {
      return notImplemented('openTab', { url, label });
    },
    switchTab({ label, index }) {
      return notImplemented('switchTab', { label, index });
    },
    getCurrentPage() {
      return notImplemented('getCurrentPage');
    },
  },
};
