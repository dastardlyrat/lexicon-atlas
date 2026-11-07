#!/usr/bin/env node
"use strict";

// Small, deterministic bridge around the official @odict/node binding.
// Set LEXICON_ODICT_MODULE to an absolute package directory when the binding
// is installed outside this project.
const fs = require("node:fs");
const crypto = require("node:crypto");
const modulePath = process.env.LEXICON_ODICT_MODULE || "@odict/node";
const {compile, OpenDictionary} = require(modulePath);

const [command, input, argument] = process.argv.slice(2);
if (!command || !input) {
  throw new Error("Usage: node odict_bridge.cjs compile INPUT.odxml OUTPUT.odict | lookup INPUT.odict TERM");
}

if (command === "compile") {
  if (!argument) throw new Error("compile requires an output path");
  const xml = fs.readFileSync(input, "utf8");
  const data = compile(xml);
  fs.writeFileSync(argument, data);
  console.log(JSON.stringify({
    input,
    output: argument,
    bytes: data.length,
    sha256: crypto.createHash("sha256").update(data).digest("hex"),
  }, null, 2));
} else if (command === "lookup") {
  if (!argument) throw new Error("lookup requires a term");
  const dictionary = new OpenDictionary(fs.readFileSync(input));
  const results = dictionary.lookup(argument);
  console.log(JSON.stringify({term: argument, results}, null, 2));
} else {
  throw new Error(`Unknown command: ${command}`);
}
