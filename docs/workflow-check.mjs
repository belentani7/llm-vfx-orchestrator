// Local-only ComfyUI API workflow shape inspection. Never uploads the user's graph.
const MAX_BYTES = 256 * 1024;
const MAX_NODES = 1024;

export function inspectWorkflowText(source) {
  if (typeof source !== 'string' || !source.trim()) {
    return { ok: false, message: 'Pega un workflow JSON antes de validarlo.' };
  }
  if (new TextEncoder().encode(source).length > MAX_BYTES) {
    return { ok: false, message: 'El JSON supera el límite local de 256 KiB.' };
  }
  let workflow;
  try {
    workflow = JSON.parse(source);
  } catch {
    return { ok: false, message: 'JSON inválido: revisa comas, comillas y llaves.' };
  }
  if (!workflow || Array.isArray(workflow) || typeof workflow !== 'object') {
    return { ok: false, message: 'El workflow debe ser un objeto JSON con nodos.' };
  }
  const entries = Object.entries(workflow);
  if (!entries.length) return { ok: false, message: 'El workflow no contiene nodos.' };
  if (entries.length > MAX_NODES) {
    return { ok: false, message: 'El workflow supera el límite local de 1024 nodos.' };
  }
  for (const [, node] of entries) {
    if (!node || Array.isArray(node) || typeof node !== 'object') {
      return { ok: false, message: 'Un nodo debe ser un objeto.' };
    }
    if (typeof node.class_type !== 'string' || !node.class_type.trim()) {
      return { ok: false, message: 'Un nodo necesita class_type.' };
    }
    if ('inputs' in node && (!node.inputs || Array.isArray(node.inputs) || typeof node.inputs !== 'object')) {
      return { ok: false, message: 'Un nodo necesita inputs como objeto.' };
    }
  }
  return {
    ok: true,
    message: `${entries.length} nodo(s) con estructura básica válida. No verifica modelos, conexiones ni ejecuta renders.`,
  };
}

if (typeof document !== 'undefined') {
  const form = document.querySelector('#workflow-check');
  if (form) {
    const input = form.querySelector('textarea');
    const output = form.querySelector('[data-workflow-result]');
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const result = inspectWorkflowText(input.value);
      output.textContent = result.message;
      output.dataset.valid = String(result.ok);
    });
  }
}
