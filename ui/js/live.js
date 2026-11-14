(function (root) {
  function extractLinks(text) {
    const found = [];
    const seen = Object.create(null);
    if (!text) return found;
    const pattern = /https?:\/\/[^\s<>"'`]+/g;
    let match;
    while ((match = pattern.exec(text))) {
      const url = match[0].replace(/[)\].,;:]+$/, "");
      if (!url || seen[url]) continue;
      seen[url] = true;
      found.push(url);
    }
    return found;
  }

  root.PyRunnerLive = { extractLinks: extractLinks };
})(typeof globalThis !== "undefined" ? globalThis : this);
