const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const staticDir = path.join(__dirname, "..", "samsung_remote", "static");
const html = fs.readFileSync(path.join(staticDir, "index.html"), "utf8");
const script = fs.readFileSync(path.join(staticDir, "remote.js"), "utf8");

test("three Kodi controls keep their labels and post through the existing handler", async () => {
  const section = html.match(/<section id="kodi" hidden>([\s\S]*?)<\/section>/)?.[1];
  assert.ok(section, "Kodi section exists and starts hidden");
  const matches = [...section.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)];
  const buttons = matches.filter(([, attrs]) => /data-kodi=/.test(attrs)).map(([, attrs, content]) => {
    const name = attrs.match(/data-kodi="([^"]+)"/)?.[1];
    return {
      name, attrs, content,
      dataset: { kodi: name },
      addEventListener(event, handler) { this[event] = handler; },
    };
  });
  assert.equal(buttons.length, 7, "four existing and exactly three new Kodi buttons");
  const added = buttons.filter((button) =>
    ["back_to_player", "stop_playing", "playlist"].includes(button.name));
  assert.deepEqual(added.map((button) => button.name),
    ["back_to_player", "stop_playing", "playlist"]);
  assert.match(added[0].content, /Back to player/);
  assert.match(added[1].attrs, /aria-label="Stop"/);
  assert.match(added[1].content, /■/);
  assert.match(added[2].content, /Playlist/);

  const requests = [];
  const kodiSection = { hidden: true };
  const elements = {
    "kodi-text": { addEventListener() {} },
    apps: { appendChild() {} },
    macros: { appendChild() {} },
    kodi: kodiSection,
  };
  const document = {
    addEventListener() {},
    querySelectorAll(selector) { return selector === "[data-kodi]" ? buttons : []; },
    getElementById(id) { return elements[id]; },
  };
  const fetch = async (url, options) => {
    if (url === "/config") return { json: async () => ({ apps: [], macros: [], kodi: true }) };
    requests.push({ url, options });
    return { ok: true };
  };
  vm.runInNewContext(script, { document, fetch, setTimeout, clearTimeout, setInterval,
    clearInterval, Date });
  await new Promise(setImmediate);
  assert.equal(kodiSection.hidden, false);
  for (const button of added) button.click();
  await new Promise(setImmediate);
  assert.deepEqual(requests.map(({ url, options }) => [url, options.method]), [
    ["/kodi/action/back_to_player", "POST"],
    ["/kodi/action/stop_playing", "POST"],
    ["/kodi/action/playlist", "POST"],
  ]);
});
