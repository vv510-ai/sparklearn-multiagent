/** Reject a build with missing, stale, corrupt, or mislabelled vocabulary audio. */
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import path from "node:path";
import assert from "node:assert/strict";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const folder = path.join(frontendRoot, "public/word-audio/v1");
const source = path.resolve(frontendRoot, "../backend/app/data");
const sha = bytes => createHash("sha256").update(bytes).digest("hex");
const sourceSha = bytes => sha(bytes.toString("utf8").replaceAll("\r\n", "\n"));
const manifest = JSON.parse(readFileSync(path.join(folder, "manifest.json"), "utf8"));
assert.equal(manifest.version, "v1");
assert.equal(manifest.source_hash_format, "UTF-8 with LF newlines");
let entries = new Map(manifest.files.filter(f => f.file.startsWith("en-US/")).map(f => [f.id, f.word]));
// The frontend-only Docker context does not contain backend source. It checks
// the pinned manifest and every asset; a full checkout also checks text parity.
if (existsSync(source)) {
  const corpusBytes = readFileSync(path.join(source, "cet6_vocabulary_v1.json"));
  const fixesBytes = readFileSync(path.join(source, "cet6_vocabulary_corrections_v1.json"));
  const corpus = JSON.parse(corpusBytes), fixes = JSON.parse(fixesBytes);
  entries = new Map(corpus.entries.filter(e => !(e.word in fixes.aliases)).map(e => [e.id, fixes.spellings[e.word] || e.word]));
  // Definitions and other metadata can change without changing pronunciation.
  // Enforce the complete ID-to-word mapping below; source hashes record provenance.
  if (manifest.corpus_sha256 !== sourceSha(corpusBytes) || manifest.corrections_sha256 !== sourceSha(fixesBytes)) {
    console.log("Vocabulary metadata changed; checking every effective word against the audio manifest.");
  }
}
assert.equal(manifest.word_count, entries.size);
assert.equal(manifest.file_count, entries.size * 2);
assert.equal(manifest.files.length, entries.size * 2);
const seen = new Set();
for (const record of manifest.files) {
  assert.match(record.id, /^cet-[a-f0-9]{24}$/);
  assert.equal(entries.get(record.id), record.word, "Audio text must match the effective word");
  assert.match(record.file, new RegExp(`^en-(US|GB)/${record.id}\\.mp3$`));
  assert.equal(seen.has(record.file), false, "Duplicate audio file");
  seen.add(record.file);
  const bytes = readFileSync(path.join(folder, record.file));
  assert.equal(bytes.length, record.bytes);
  assert.equal(sha(bytes), record.sha256, `Corrupt audio: ${record.file}`);
  assert.ok(bytes.length > 500 && record.duration >= .15 && record.peak >= 100, "Audio must contain audible samples");
}
for (const accent of ["en-US", "en-GB"]) {
  assert.equal(readdirSync(path.join(folder, accent)).length, entries.size);
  for (const id of entries.keys()) assert.ok(seen.has(`${accent}/${id}.mp3`), `Missing ${accent} ${id}`);
}
console.log(`Word audio verified: ${entries.size} words, ${seen.size} MP3 files, both accents.`);
