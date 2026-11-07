const STOPWORDS = new Set("a an and are as at be by for from in into is it of on or that the their this to was with".split(" "));

function tokens(value) {
  return new Set((String(value || "").toLocaleLowerCase().match(/[a-z][a-z'-]{2,}/g) || [])
    .filter((token) => !STOPWORDS.has(token)));
}

function root(token) {
  return token.replace(/(ingly|edly|ing|ed|es|s)$/i, "");
}

function collectCandidates({senses = [], wiktionary = {status: "idle", groups: []}, gcide = [], posNames = {}}) {
  const candidates = [];
  senses.forEach((sense) => {
    if (!sense.data?.definition) return;
    candidates.push({
      source: "Open English WordNet",
      kind: "WordNet",
      pos: posNames[sense.data.pos] || sense.data.pos,
      definition: sense.data.definition,
      example: sense.data.examples?.[0] || "",
      ref: sense.data.id,
      weight: 5,
    });
  });
  if (wiktionary.status === "local") {
    wiktionary.groups.forEach((entry, entryIndex) => (entry.s || []).forEach((sense, senseIndex) => {
      const definition = (sense.glosses || []).join("; ");
      if (!definition) return;
      candidates.push({
        source: "Wiktionary",
        kind: "Wiktionary",
        pos: entry.p || "entry",
        definition,
        example: sense.examples?.[0]?.text || "",
        ref: `wiktionary-${entryIndex + 1}-${senseIndex + 1}`,
        weight: 3,
      });
    }));
  }
  gcide.forEach((entry, entryIndex) => (entry.d || []).forEach((definition, definitionIndex) => {
    if (!definition) return;
    candidates.push({
      source: "GCIDE",
      kind: "GCIDE",
      pos: (entry.p || []).join(" · ") || "entry",
      definition,
      example: "",
      ref: `gcide-${entryIndex + 1}-${definitionIndex + 1}`,
      weight: 2,
    });
  }));
  return candidates;
}

function rankCandidates(candidates, term, context) {
  const contextTokens = new Set([...tokens(context)].map(root));
  contextTokens.delete(root(String(term || "").toLocaleLowerCase()));
  const tokenSets = candidates.map((candidate) => tokens(candidate.definition));
  return candidates.map((candidate, index) => {
    let agreement = 0;
    tokenSets.forEach((other, otherIndex) => {
      if (index === otherIndex) return;
      let overlap = 0;
      tokenSets[index].forEach((token) => { if (other.has(token)) overlap += 1; });
      agreement += Math.min(overlap, 4);
    });
    let contextMatch = 0;
    const candidateRoots = new Set([...tokenSets[index]].map(root));
    contextTokens.forEach((token) => { if (candidateRoots.has(token)) contextMatch += 1; });
    const score = candidate.weight * 10 + Math.min(agreement, 12) + contextMatch * 7;
    return {...candidate, score, agreement, contextMatch};
  }).sort((left, right) => right.score - left.score || left.source.localeCompare(right.source) || left.ref.localeCompare(right.ref));
}

function sharedCues(ranked) {
  const counts = new Map();
  ranked.slice(0, 12).forEach((candidate) => tokens(candidate.definition).forEach((token) => counts.set(token, (counts.get(token) || 0) + 1)));
  return [...counts.entries()]
    .filter(([, count]) => count > 1)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 8)
    .map(([token]) => token);
}

export function buildSynthesis({term, senses, wiktionary, gcide, context = "", posNames}) {
  const candidates = collectCandidates({senses, wiktionary, gcide, posNames});
  const ranked = rankCandidates(candidates, term, context);
  const best = ranked[0] || null;
  const trimmedContext = context.trim();
  return {
    candidates,
    ranked,
    best,
    cues: sharedCues(ranked),
    sourceCount: new Set(candidates.map((candidate) => candidate.source)).size,
    context: trimmedContext,
    contextLine: trimmedContext
      ? `Context overlap was counted against: “${trimmedContext}”`
      : "No context was supplied, so the ranking uses source weight and cross-source lexical overlap.",
    proposal: best
      ? trimmedContext
        ? `In the supplied context, the leading lexical candidate is “${best.definition}” (${best.source}, ${best.pos}).`
        : `The leading lexical candidate is “${best.definition}” (${best.source}, ${best.pos}).`
      : "No lexical candidate is attached for this spelling.",
  };
}
