import test from 'node:test';
import assert from 'node:assert/strict';
import { inspectWorkflowText } from '../docs/workflow-check.mjs';

test('accepts a minimal ComfyUI API workflow without contacting providers', () => {
  const result = inspectWorkflowText(JSON.stringify({ '3': { class_type: 'KSampler', inputs: {} } }));
  assert.equal(result.ok, true);
  assert.match(result.message, /1 nodo/);
  assert.match(result.message, /No verifica modelos/);
});

test('rejects malformed, empty, array, and null workflows', () => {
  for (const source of ['', '{bad', '{}', '[]', 'null']) {
    assert.equal(inspectWorkflowText(source).ok, false, source);
  }
});

test('rejects missing node types and malformed inputs', () => {
  for (const node of [{ inputs: {} }, { class_type: '  ' }, { class_type: 'X', inputs: [] }, null]) {
    assert.equal(inspectWorkflowText(JSON.stringify({ '1': node })).ok, false);
  }
});

test('limits UTF-8 input size before parsing', () => {
  assert.equal(inspectWorkflowText('é'.repeat(150000)).ok, false);
});

test('limits number of nodes', () => {
  const graph = Object.fromEntries(Array.from({ length: 1025 }, (_, i) => [String(i), { class_type: 'X' }]));
  assert.equal(inspectWorkflowText(JSON.stringify(graph)).ok, false);
});

test('does not echo prompts, URLs or secrets in errors', () => {
  const secret = 'private-user-voice-and-api-key';
  const result = inspectWorkflowText(JSON.stringify({ [secret]: { inputs: {} } }));
  // Node identifiers can be user data: errors must not reflect them.
  assert.equal(result.ok, false);
  assert.equal(result.message.includes(secret), false);
});
